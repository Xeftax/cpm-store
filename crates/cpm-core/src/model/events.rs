//! Storage change notifications (strict synchronization).
//!
//! `NmsEvent` / `NmsEventList` per REST-NMS §5.3.2 "Type: NmsEvent" / §5.3.2 "Type: NmsEventList", used by the
//! subscription/notification mechanism that strict synchronization relies on
//! (spec §5.5, §6.3.2). The `restartToken` applies to the box as a whole
//! (REST-NMS §5.1.4.3); `lastModSeq` handles reordering/duplication
//! (REST-NMS §5.1.4.4); `index` handles loss (REST-NMS §5.1.4.5).

use rest_json::rest_json;
use serde::{Deserialize, Serialize};

use super::attribute::AttributeList;
use super::flags::FlagList;
use super::imdn::ImdnList;

// ==== Event types (REST-NMS §5.3.2 "Type: NmsEvent"–§5.3.2 "Type: ResetBox") ====
/// `Link` — `common:Link` ([REST_NetAPI_Common]); `rel` values "folder" and
/// "nmsSubscription" are defined by REST-NMS §5.3.4.
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Link {
    pub href: String,
    #[serde(default)]
    pub rel: Option<String>,
}

/// An object that has been deleted or expired — REST-NMS §5.3.2.27.
#[rest_json(acronyms("URL"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeletedObject {
    pub resource_url: String,
    #[serde(default)]
    pub attributes: Option<AttributeList>,
    #[serde(default, deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
    pub correlation_id: Option<String>,
    pub correlation_tag: Option<String>,
}

/// A folder that has been deleted or expired — REST-NMS §5.3.2.28.
#[rest_json(acronyms("URL"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeletedFolder {
    pub resource_url: String,
    #[serde(default, deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
}

/// A new or changed object — REST-NMS §5.3.2.29. Object creation is reported
/// with a `changedObject` event (REST-NMS §5.3.2 "Type: NmsEvent").
#[rest_json(acronyms("URL"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangedObject {
    pub parent_folder: String,
    pub flags: FlagList,
    pub imdns: Option<ImdnList>,
    pub resource_url: String,
    pub attributes: Option<AttributeList>,
    #[serde(default, deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
    pub correlation_id: Option<String>,
    pub correlation_tag: Option<String>,
}

/// A new or changed folder — REST-NMS §5.3.2.30.
#[rest_json(acronyms("URL"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangedFolder {
    pub parent_folder: String,
    pub resource_url: String,
    pub name: String,
    #[serde(default, deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
}

/// Box reset — REST-NMS §5.3.2 "Type: ResetBox" (empty type; the client MUST re-run a
/// first-time sync, REST-NMS §5.1.4.2.1).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResetBox;

/// `NmsEvent` — REST-NMS §5.3.2 "Type: NmsEvent". XSD "choice": exactly one variant.
/// Serialized as an externally tagged object, e.g. `{"changedObject": {...}}`.
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum NmsEvent {
    DeletedObject(DeletedObject),
    DeletedFolder(DeletedFolder),
    ExpiredObject(DeletedObject),
    ExpiredFolder(DeletedFolder),
    ChangedObject(ChangedObject),
    ChangedFolder(ChangedFolder),
    ResetBox(ResetBox),
}

// ==== Event list (REST-NMS §5.3.2 "Type: NmsEventList") ====
/// `NmsEventList` — REST-NMS §5.3.2 "Type: NmsEventList" (JSON root element `nmsEventList`),
/// body of notification requests (spec §7.3.1.2).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct NmsEventList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub nms_event: Vec<NmsEvent>,
    pub callback_data: Option<String>,
    /// Index of this notification list in the subscription (REST-NMS §5.1.4.5).
    #[serde(deserialize_with = "super::de_u64_or_str")]
    pub index: Option<u64>,
    /// Restart token representing the point after the notified change(s)
    /// (REST-NMS §5.1.4.3).
    pub restart_token: Option<String>,
    pub link: Option<Vec<Link>>,
}

/// Root element `nmsEventList` wrapping an [`NmsEventList`].
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NmsEventListEnvelope {
    pub nms_event_list: NmsEventList,
}

// ==== Tests ====
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nms_event_choice_serializes_as_external_tag() {
        // REST-NMS §5.3.2 "Type: NmsEvent" XSD choice -> {"changedObject": {...}}.
        let ev = NmsEvent::ChangedObject(ChangedObject {
            parent_folder: "http://s/folders/f1".into(),
            flags: FlagList::new(),
            imdns: None,
            resource_url: "http://s/objects/o1".into(),
            attributes: None,
            last_mod_seq: Some(9),
            correlation_id: None,
            correlation_tag: None,
        });
        let v = serde_json::to_value(&ev).unwrap();
        assert!(v.get("changedObject").is_some());
        let back: NmsEvent = serde_json::from_value(v).unwrap();
        assert_eq!(back, ev);
    }

    #[test]
    fn nms_event_list_json_round_trip() {
        let v = serde_json::json!({"nmsEventList": {
            "nmsEvent": [
                {"changedObject": {
                    "parentFolder": "http://s/folders/f1",
                    "flags": {"flag": ["\\Seen"]},
                    "resourceURL": "http://s/objects/o1",
                    "lastModSeq": 9
                }},
                {"deletedFolder": {"resourceURL": "http://s/folders/f2", "lastModSeq": 10}}
            ],
            "index": 3,
            "restartToken": "rt-abc"
        }});
        let env: NmsEventListEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.nms_event_list.nms_event.len(), 2);
        assert_eq!(env.nms_event_list.index, Some(3));
        assert_eq!(env.nms_event_list.restart_token.as_deref(), Some("rt-abc"));
        let v1 = serde_json::to_value(&env).unwrap();
        let env2: NmsEventListEnvelope = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&env2).unwrap(), v1);
    }
}
