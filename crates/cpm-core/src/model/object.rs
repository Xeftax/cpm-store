//! NMS object — the message object of the CPM Message Storage.
//!
//! `NmsObject` per REST-NMS §5.3.2.1 "Type: Object"; the CPM message object is
//! stored/retrieved through it (spec §5.3.1). The `{objectId}` is a string
//! unique in the context of the NMS box (spec §5.3.1.1) and, combined with the
//! box ID, permanently identifies one stored object (spec §5.4).

use jiff::Timestamp;
use rest_json::rest_json;
use serde::{Deserialize, Serialize};

use super::attribute::AttributeList;
use super::flags::FlagList;
use super::imdn::ImdnList;
use super::mapping::ObjectId;

// ==== Parent reference (REST-NMS §5.3.2.1) ====
/// How the parent folder of an object/folder is referenced in a request:
/// XSD "choice" of `parentFolder` (resource URL) or `parentFolderPath`
/// (hierarchical path) — REST-NMS §5.3.2.1.
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ParentRef {
    FolderUrl(String),
    FolderPath(String),
}

// ==== Payload parts (REST-NMS §5.3.2.7) ====
/// Information about an individual payload part — REST-NMS §5.3.2.7
/// "Type: PayloadPartInfo".
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct PayloadPartInfo {
    /// Link to the stored content (`.../payloadParts/{id}` or external CDN).
    pub href: String,
    /// MIME content type of the stored content.
    pub content_type: String,
    #[serde(deserialize_with = "super::de_u64_or_str")]
    pub size: Option<u64>,
    /// Content-ID of the part ([RFC2045], without angle brackets), used by
    /// `cid:` URLs ([RFC2392]).
    pub content_id: Option<String>,
    pub content_location: Option<String>,
    /// Content-Disposition ([RFC2183]), unfolded.
    pub content_disposition: Option<String>,
    /// File-Icon: a Content-ID URL pointing to a thumbnail payload part
    /// ([RFC5547]).
    pub file_icon: Option<String>,
    /// Beyond this date the `href` of externally referenced content is no
    /// longer valid.
    pub href_expiry: Option<Timestamp>,
}

// ==== NmsObject (REST-NMS §5.3.2.1) ====
/// `NmsObject` — REST-NMS §5.3.2.1 "Type: Object" (JSON root element `object`).
///
/// The CPM message object adds no field of its own over the NMS object: its
/// metadata is carried by `attributes` (mapping table of spec §5.3.1.2) and
/// its payload by `payloadPart` / `payloadURL` (spec §5.3.1, annex C).
#[rest_json(default, acronyms("URL"))]
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct NmsObject {
    /// Choice with `parent_folder_path` (REST-NMS §5.3.2.1). The server MUST
    /// include it in responses.
    pub parent_folder: Option<String>,
    /// Choice with `parent_folder` (REST-NMS §5.3.2.1). The server MUST NOT
    /// include it in responses.
    pub parent_folder_path: Option<String>,
    /// Attributes associated with the object (REST-NMS §5.3.2.1/§5.3.2.6).
    pub attributes: AttributeList,
    /// Flags associated with the object (spec §5.6).
    pub flags: FlagList,
    pub imdns: Option<ImdnList>,
    /// Self-referring URL; MUST be included in responses and notifications.
    pub resource_url: Option<String>,
    /// Location of the object in the hierarchical storage (REST-NMS §5.1.1).
    pub path: Option<String>,
    /// Location of the entire payload; present iff the object is non-empty
    /// (REST-NMS §5.3.2.1).
    pub payload_url: Option<String>,
    /// Individual payload parts; omitted when the object is empty.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub payload_part: Vec<PayloadPartInfo>,
    /// Last mod-sequence value (strict sync, REST-NMS §5.1.4.4; spec §5.4).
    #[serde(deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
    /// Correlation ID (REST-NMS §5.1.13.2).
    pub correlation_id: Option<String>,
    /// Correlation tag (REST-NMS §5.1.13.3).
    pub correlation_tag: Option<String>,
}

impl NmsObject {
    /// The object ID, i.e. the last path segment of `resourceURL`
    /// (spec §5.3.1.1).
    pub fn object_id(&self) -> Option<ObjectId> {
        self.resource_url
            .as_deref()
            .and_then(ObjectId::from_resource_url)
    }

    /// An object with no payload parts and no payload URL is "empty"
    /// (REST-NMS §5.3.2.1) — e.g. IMDN objects (spec §5.3.10).
    pub fn is_empty(&self) -> bool {
        self.payload_part.is_empty() && self.payload_url.is_none()
    }
}

// ==== Envelopes and lists (REST-NMS §5.3.2 "Type: ObjectList") ====
/// Root element `object` wrapping an [`NmsObject`] (REST-NMS §5.3.2.1).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ObjectEnvelope {
    pub object: NmsObject,
}

/// `ObjectList` — REST-NMS §5.3.2 "Type: ObjectList" (JSON root element `objectList`).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct ObjectList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub object: Vec<NmsObject>,
    /// Present when more objects are available (REST-NMS §5.1.11).
    pub cursor: Option<String>,
    /// Returned in response to a CreatedObjects search (REST-NMS §5.3.2 "Type: ObjectList").
    pub creation_cursor: Option<String>,
}

/// Root element `objectList` wrapping an [`ObjectList`].
#[rest_json]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ObjectListEnvelope {
    pub object_list: ObjectList,
}

// ==== Client-side draft / update (spec §7.3.3) ====
/// Client-side draft of a `POST /objects` request: the `root-fields` part plus
/// the attachment parts (spec §7.3.3.1, annex C).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ObjectDraft {
    pub parent: Option<ParentRef>,
    pub attributes: AttributeList,
    pub flags: FlagList,
    pub correlation_id: Option<String>,
    pub correlation_tag: Option<String>,
    /// Attachment payload parts, sent as the multipart body of the object.
    pub payload: Vec<DraftPayloadPart>,
}

/// One attachment of an [`ObjectDraft`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DraftPayloadPart {
    pub content_type: String,
    pub body: Vec<u8>,
    pub content_disposition: Option<String>,
    pub content_id: Option<String>,
}

/// Client-side `PUT /objects/{objectId}` update (spec §6.4.1, §7.3.3).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ObjectUpdate {
    pub parent: Option<ParentRef>,
    pub attributes: Option<AttributeList>,
    pub flags: Option<FlagList>,
    pub correlation_id: Option<String>,
    pub correlation_tag: Option<String>,
}

// ==== Tests ====
#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::flags::MetadataFlag;
    use crate::model::kind::CpmObjectKind;

    #[test]
    fn parses_annex_c_get_example_shape() {
        // GET response of spec annex C (message object obj542).
        let v = serde_json::json!({"object": {
            "parentFolder": "http://server/nms/v1/base/tel:+12021308085/folders/UGZa5FY4o1S1oTSQSQC",
            "attributes": {"attribute": [
                {"name": "Subject", "value": ["the weather will be fine today "]},
                {"name": "Message-Context", "value": ["multimedia-message"]},
                {"name": "Direction", "value": ["IN"]}
            ]},
            "flags": {"flag": ["\\Seen", "\\Flagged"]},
            "resourceURL": "http://server/nms/v1/base/tel:+12021308085/objects/obj542",
            "path": "/main/conversation5/obj542",
            "payloadURL": "http://server/nms/v1/base/tel:+12021308085/objects/obj542/payload",
            "payloadPart": [
                {"contentType": "text/plain", "size": 48,
                 "href": "http://server/nms/v1/base/tel:+12021308085/objects/obj542/payloadParts/blob123"},
                {"contentType": "image/gif", "size": 1024,
                 "href": "http://server/nms/v1/base/tel:+12021308085/objects/obj542/payloadParts/blob457"}
            ],
            "lastModSeq": 48
        }});
        let env: ObjectEnvelope = serde_json::from_value(v).unwrap();
        let o = &env.object;
        assert_eq!(o.object_id().as_ref().map(ObjectId::as_str), Some("obj542"));
        assert_eq!(o.cpm_kind(), CpmObjectKind::Message);
        assert!(o.flags.contains(&MetadataFlag::Seen));
        assert!(o.flags.contains(&MetadataFlag::Flagged));
        assert_eq!(o.payload_part.len(), 2);
        assert_eq!(o.last_mod_seq, Some(48));
        assert!(!o.is_empty());
        assert_eq!(
            o.attributes.message_context(),
            Some(crate::model::kind::MessageContext::MultimediaMessage)
        );
    }

    #[test]
    fn envelope_round_trip_is_fixed_point() {
        let v = serde_json::json!({"object": {
            "attributes": {"attribute": [{"name": "Message-Context", "value": ["imdn-message"]}]},
            "flags": {"flag": ["\\Seen"]},
            "resourceURL": "http://server/nms/v1/base/tel:+1/objects/imdn1"
        }});
        let env: ObjectEnvelope = serde_json::from_value(v).unwrap();
        assert!(env.object.is_empty()); // IMDN objects have no payload (spec §5.3.10)
        assert_eq!(env.object.cpm_kind(), CpmObjectKind::Imdn);
        let v1 = serde_json::to_value(&env).unwrap();
        let env2: ObjectEnvelope = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&env2).unwrap(), v1);
    }
}
