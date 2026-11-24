//! IMDN (disposition notification) data — REST-NMS §5.3.2.36 "Type: ImdnInfo",
//! "Type: Imdn" and §5.3.2.37 "Type: ImdnList". An IMDN object is stored as a
//! message object with no payload whose content is realized by NMS attributes
//! (spec §5.3.10, RFC 5438).

use jiff::Timestamp;
use rest_json::rest_json;
use serde::{Deserialize, Serialize};

/// IMDN information — REST-NMS §5.3.2.36.
///
/// `type` is the disposition type/status per RFC 5438 (e.g. "delivered",
/// "displayed"); CPM-REST §5.3.10 defines the attribute mapping.
#[rest_json(rename(disposition_type = "type"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImdnInfo {
    pub disposition_type: String,
    /// xsd:dateTimeStamp — when the IMDN was sent.
    pub date: Timestamp,
}

/// Individual IMDN — REST-NMS "Type: Imdn".
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Imdn {
    /// Address (sip/tel/acr URI) of the user that sent the IMDN.
    pub original_to: String,
    #[serde(default, deserialize_with = "super::one_or_many")]
    pub imdn_info: Vec<ImdnInfo>,
}

/// `ImdnList` — REST-NMS §5.3.2.37.
///
/// JSON shape: `{"imdn": [...], "lastModSeq": ..., "resourceURL": ...}`.
#[rest_json(default, acronyms("URL"))]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImdnList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub imdn: Vec<Imdn>,
    #[serde(deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
    pub resource_url: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn imdn_list_json_round_trip() {
        let v = serde_json::json!({
            "imdn": [{
                "originalTo": "tel:+15195551212",
                "imdnInfo": [{"type": "displayed", "date": "2012-06-13T16:39:57-05:00"}]
            }],
            "lastModSeq": 12
        });
        let list: ImdnList = serde_json::from_value(v.clone()).unwrap();
        assert_eq!(list.imdn.len(), 1);
        assert_eq!(list.imdn[0].original_to, "tel:+15195551212");
        assert_eq!(list.imdn[0].imdn_info[0].disposition_type, "displayed");
        assert_eq!(list.last_mod_seq, Some(12));
        let v1 = serde_json::to_value(&list).unwrap();
        let list2: ImdnList = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&list2).unwrap(), v1);
    }
}
