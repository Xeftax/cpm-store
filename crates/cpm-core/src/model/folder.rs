//! NMS folder and references.
//!
//! `Folder` per REST-NMS §5.3.2.8 "Type: Folder"; `Reference` per §5.3.2 "Type: Reference".
//! CPM folder kinds (conversation history folder §5.3.6, session history
//! folder §5.3.7, user folder §5.3.8) are realized via the NMS folder concept
//! and carry no machine-readable marker over the REST binding — classification
//! by path/name is left to the host.

use rest_json::rest_json;
use serde::{Deserialize, Serialize};

use super::attribute::AttributeList;

// ==== References (REST-NMS §5.3.2 "Type: FolderReferenceList"–§5.3.2 "Type: ReferenceList") ====
/// Reference to a stored object or folder — REST-NMS §5.3.2 "Type: Reference"
/// (JSON root element `reference`).
#[rest_json(acronyms("URL"))]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Reference {
    /// The resource URL (mandatory, REST-NMS §5.3.2 "Type: Reference").
    pub resource_url: String,
    /// Location in the hierarchical storage.
    #[serde(default)]
    pub path: Option<String>,
}

impl Reference {
    pub fn new(resource_url: impl Into<String>) -> Self {
        Reference {
            resource_url: resource_url.into(),
            path: None,
        }
    }
}

/// `FolderReferenceList` — REST-NMS §5.3.2 "Type: FolderReferenceList"
/// (JSON shape `{"folderReference": [...]}`).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FolderReferenceList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub folder_reference: Vec<Reference>,
}

/// `ObjectReferenceList` — REST-NMS §5.3.2 "Type: ObjectReferenceList"
/// (JSON shape `{"objectReference": [...]}`).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObjectReferenceList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub object_reference: Vec<Reference>,
}

/// `ReferenceList` — REST-NMS §5.3.2 "Type: ReferenceList" (folders and/or objects).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReferenceList {
    pub folders: FolderReferenceList,
    pub objects: ObjectReferenceList,
}

/// `TargetSourceRef` — REST-NMS §5.3.2 "Type: TargetSourceRef", body of move/copy operations
/// (spec §7.3.2.4/§7.3.2.5, §7.3.3.4).
#[rest_json]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TargetSourceRef {
    /// Reference to the target folder.
    pub target_ref: Reference,
    /// References to the source object(s)/folder(s).
    pub source_refs: ReferenceList,
}

// ==== Folder (REST-NMS §5.3.2.8) ====
/// `Folder` — REST-NMS §5.3.2.8 "Type: Folder" (JSON root element `folder`).
#[rest_json(default, acronyms("URL"))]
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Folder {
    /// Choice with `parent_folder_path` (REST-NMS §5.3.2.8).
    pub parent_folder: Option<String>,
    pub parent_folder_path: Option<String>,
    /// Folder attributes; standard names in REST-NMS Appendix J ("Root",
    /// "Name", ...), RCS names in Appendix K ("MsgCount", ...).
    pub attributes: AttributeList,
    pub resource_url: Option<String>,
    pub path: Option<String>,
    /// Folder name; MUST NOT contain "/" (U+002F), the hierarchy delimiter
    /// (REST-NMS §5.3.2.8).
    pub name: Option<String>,
    /// Last mod-sequence value (strict sync, REST-NMS §5.1.4.4).
    #[serde(deserialize_with = "super::de_u64_or_str")]
    pub last_mod_seq: Option<u64>,
    /// Present when more sub-folders/objects are available (REST-NMS §5.1.11).
    pub cursor: Option<String>,
    pub sub_folders: Option<FolderReferenceList>,
    pub objects: Option<ObjectReferenceList>,
}

// ==== Folder lists (REST-NMS §5.3.2 "Type: FolderList", §5.3.2 "Type: PathList") ====
/// Root element `folder` wrapping a [`Folder`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FolderEnvelope {
    pub folder: Folder,
}

/// `FolderList` — REST-NMS §5.3.2 "Type: FolderList" (JSON root element `folderList`).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct FolderList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub folder: Vec<Folder>,
    pub cursor: Option<String>,
}

/// `PathList` — REST-NMS §5.3.2 "Type: PathList" (JSON root element `pathList`).
#[rest_json(default)]
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PathList {
    #[serde(deserialize_with = "super::one_or_many")]
    pub path: Vec<String>,
}

/// Root element `folderList` wrapping a [`FolderList`].
#[rest_json]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FolderListEnvelope {
    pub folder_list: FolderList,
}

// ==== Tests ====
#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::attribute::Attribute;

    #[test]
    fn folder_json_round_trip() {
        // Shape of a folder resource (REST-NMS §5.3.2.8).
        let v = serde_json::json!({"folder": {
            "parentFolder": "http://server/nms/v1/base/tel:+1/folders/root",
            "attributes": {"attribute": [
                {"name": "Name", "value": ["conversation5"]},
                {"name": "MsgCount", "value": ["3"]}
            ]},
            "resourceURL": "http://server/nms/v1/base/tel:+1/folders/conv5",
            "path": "/main/conversation5",
            "name": "conversation5",
            "lastModSeq": 7,
            "objects": {"objectReference": [
                {"resourceURL": "http://server/nms/v1/base/tel:+1/objects/obj542",
                 "path": "/main/conversation5/obj542"}
            ]}
        }});
        let env: FolderEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.folder.name.as_deref(), Some("conversation5"));
        assert_eq!(env.folder.last_mod_seq, Some(7));
        let objs = env.folder.objects.as_ref().unwrap();
        assert_eq!(objs.object_reference.len(), 1);
        assert_eq!(env.folder.attributes.first_value("msgcount"), Some("3"));
        let v1 = serde_json::to_value(&env).unwrap();
        let env2: FolderEnvelope = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&env2).unwrap(), v1);
    }

    #[test]
    fn folder_list_envelope() {
        let v = serde_json::json!({"folderList": {
            "folder": [{"name": "a", "attributes": {"attribute": []}}],
            "cursor": "cur1"
        }});
        let env: FolderListEnvelope = serde_json::from_value(v).unwrap();
        assert_eq!(env.folder_list.folder.len(), 1);
        assert_eq!(env.folder_list.cursor.as_deref(), Some("cur1"));
    }

    #[test]
    fn attribute_list_is_shared() {
        let f = Folder {
            attributes: AttributeList::from(vec![Attribute::new("Root", vec!["Yes".to_owned()])]),
            ..Default::default()
        };
        assert_eq!(f.attributes.first_value("root"), Some("Yes"));
    }
}
