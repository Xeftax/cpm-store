//! Search / selection / sort criteria and bulk operation payloads.
//!
//! Types per REST-NMS §5.3.2.15–§5.3.2.21 and enumerations §5.3.3.1–§5.3.3.5.
//! Used by the object/folder search and bulk operations of spec §6.4.1, §7.3.3.

use serde::{Deserialize, Serialize};

use super::flags::FlagList;
use super::folder::{ObjectReferenceList, Reference};
use super::imdn::ImdnInfo;

/// `SearchTypeEnum` — REST-NMS §5.3.3.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SearchType {
    Date,
    Attribute,
    AllTextAttributes,
    Flag,
    WholeWord,
    VanishedObjects,
    CreatedObjects,
    PresetSearch,
    FileName,
}

/// `LogicalOperatorEnum` — REST-NMS §5.3.3.2 (default AND when absent,
/// REST-NMS §5.3.2.18).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum LogicalOperator {
    And,
    Or,
    Not,
}

/// `SortTypeEnum` — REST-NMS §5.3.3.3.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SortType {
    Date,
    Attribute,
}

/// `SortOrderEnum` — REST-NMS §5.3.3.4 (default Descending, §5.3.2.21).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SortOrder {
    Ascending,
    Descending,
}

/// `OperationEnum` — REST-NMS §5.3.3.5, flag operation of a bulk update
/// (REST-NMS §5.3.2.15).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Operation {
    AddFlag,
    RemoveFlag,
}

/// `SearchCriterion` — REST-NMS §5.3.2.19.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchCriterion {
    #[serde(rename = "type")]
    pub search_type: SearchType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
}

/// `SearchCriteria` — REST-NMS §5.3.2.18 (JSON root element `searchCriteria`).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct SearchCriteria {
    #[serde(deserialize_with = "super::one_or_many")]
    pub criterion: Vec<SearchCriterion>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub operator: Option<LogicalOperator>,
}

/// `SortCriterion` — REST-NMS §5.3.2.21.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SortCriterion {
    #[serde(rename = "type")]
    pub sort_type: SortType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub order: Option<SortOrder>,
}

/// `SortCriteria` — REST-NMS §5.3.2.20.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct SortCriteria {
    #[serde(deserialize_with = "super::one_or_many")]
    pub criterion: Vec<SortCriterion>,
}

/// `SelectionCriteria` — REST-NMS §5.3.2.17 (JSON root element
/// `selectionCriteria`); body of search/list requests (spec §7.3.2.1,
/// §7.3.3.3).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct SelectionCriteria {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from_cursor: Option<String>,
    /// Maximum number of entries to return (mandatory, REST-NMS §5.3.2.17).
    #[serde(default)]
    pub max_entries: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_criteria: Option<SearchCriteria>,
    /// Folder at which the search starts (scope = subtree).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub search_scope: Option<Reference>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_bool_or_str"
    )]
    pub non_recursive_scope: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sort_criteria: Option<SortCriteria>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_bool_or_str"
    )]
    pub inline_imdn: Option<bool>,
}

/// `BulkUpdate` — REST-NMS §5.3.2.15 (JSON root element `bulkUpdate`); body of
/// the bulk update operation (spec §7.3.3.7, §6.6.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BulkUpdate {
    /// Choice with `selection_criteria` (REST-NMS §5.3.2.15).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub objects: Option<ObjectReferenceList>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selection_criteria: Option<SelectionCriteria>,
    pub operation: Operation,
    /// MUST be present when `operation` is AddFlag/RemoveFlag (§5.3.2.15).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub flags: Option<FlagList>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub imdns: Option<Vec<ImdnInfo>>,
}

/// `BulkDelete` — REST-NMS §5.3.2.16 (JSON root element `bulkDelete`); body of
/// the bulk delete operation (spec §7.3.3.6).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct BulkDelete {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub objects: Option<ObjectReferenceList>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selection_criteria: Option<SelectionCriteria>,
}

/// `Response` — REST-NMS §5.3.2.33: status of a single operation in a bulk
/// operation. XSD "choice" of `success` (Reference) or `failure` (RequestError).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BulkResponse {
    /// HTTP status code (e.g. 200, 400, 404).
    #[serde(deserialize_with = "super::de_u16_or_str")]
    pub code: u16,
    /// HTTP status string (e.g. "OK", "Not Found").
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub success: Option<Reference>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub failure: Option<RequestError>,
}

/// Kind of a `common:RequestError` exception ([REST_NetAPI_Common]):
/// `policyException` or `serviceException`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum RequestErrorKind {
    #[serde(rename = "policyException")]
    Policy,
    #[serde(rename = "serviceException")]
    Service,
}

/// `common:RequestError` exception content ([REST_NetAPI_Common]):
/// `messageId`, human-readable `text` and optional `variables`.
///
/// JSON appears either embedded (`{"policyException": {...}}`) or as the
/// standalone root element (`{"requestError": {"policyException": {...}}}`);
/// both forms are accepted on parse (see the REST-NMS Appendix D examples).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestError {
    pub kind: RequestErrorKind,
    pub message_id: String,
    pub text: Option<String>,
    pub variables: Option<Vec<String>>,
}

impl Serialize for RequestError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct Ex<'a> {
            message_id: &'a str,
            #[serde(skip_serializing_if = "Option::is_none")]
            text: &'a Option<String>,
            #[serde(skip_serializing_if = "Option::is_none")]
            variables: &'a Option<Vec<String>>,
        }
        let mut map = serializer.serialize_map(Some(1))?;
        let kind = match self.kind {
            RequestErrorKind::Policy => "policyException",
            RequestErrorKind::Service => "serviceException",
        };
        map.serialize_entry(
            kind,
            &Ex {
                message_id: &self.message_id,
                text: &self.text,
                variables: &self.variables,
            },
        )?;
        map.end()
    }
}

impl<'de> Deserialize<'de> for RequestError {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        use serde::de::Error as _;
        let v = serde_json::Value::deserialize(deserializer)?;
        let mut inner = v;
        if let Some(wrapped) = inner.get("requestError") {
            inner = wrapped.clone();
        }
        let (kind, ex) = if let Some(e) = inner.get("policyException") {
            (RequestErrorKind::Policy, e.clone())
        } else if let Some(e) = inner.get("serviceException") {
            (RequestErrorKind::Service, e.clone())
        } else {
            return Err(D::Error::custom(
                "requestError: expected policyException or serviceException",
            ));
        };
        #[derive(Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct Ex {
            message_id: String,
            #[serde(default)]
            text: Option<String>,
            #[serde(default)]
            variables: Option<Vec<String>>,
        }
        let ex: Ex = serde_json::from_value(ex).map_err(D::Error::custom)?;
        Ok(RequestError {
            kind,
            message_id: ex.message_id,
            text: ex.text,
            variables: ex.variables,
        })
    }
}

/// `BulkResponseList` — REST-NMS §5.3.2.34 (JSON root element
/// `bulkResponseList`).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct BulkResponseList {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_bool_or_str"
    )]
    pub all_success: Option<bool>,
    #[serde(deserialize_with = "super::one_or_many")]
    pub response: Vec<BulkResponse>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cursor: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn search_criteria_json_round_trip() {
        let v = serde_json::json!({"searchCriteria": {
            "criterion": [
                {"type": "Flag", "name": "\\Seen", "value": "false"},
                {"type": "Attribute", "name": "Message-Context", "value": "chat-message"}
            ],
            "operator": "And"
        }});
        let crit: SearchCriteria = serde_json::from_value(
            serde_json::json!({"criterion": v["searchCriteria"]["criterion"], "operator": "And"}),
        )
        .unwrap();
        assert_eq!(crit.criterion.len(), 2);
        assert_eq!(crit.criterion[0].search_type, SearchType::Flag);
        assert_eq!(crit.operator, Some(LogicalOperator::And));
    }

    #[test]
    fn bulk_update_json_shape() {
        let v = serde_json::json!({"bulkUpdate": {
            "objects": {"objectReference": [
                {"resourceURL": "http://server/nms/v1/base/tel:+1/objects/obj1"}
            ]},
            "operation": "AddFlag",
            "flags": {"flag": ["\\Flagged"]}
        }});
        let upd: BulkUpdate = serde_json::from_value(v["bulkUpdate"].clone()).unwrap();
        assert_eq!(upd.operation, Operation::AddFlag);
        assert!(
            upd.flags
                .as_ref()
                .unwrap()
                .contains(&crate::model::flags::MetadataFlag::Flagged)
        );
        let v1 = serde_json::to_value(&upd).unwrap();
        let upd2: BulkUpdate = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&upd2).unwrap(), v1);
    }
}
