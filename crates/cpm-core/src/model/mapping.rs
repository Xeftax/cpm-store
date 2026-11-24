//! Mapping between NMS object IDs and host-local message IDs (ADR D3).
//!
//! The combination of box ID and object ID permanently and persistently
//! refers to one and only one stored object (spec §5.4); the `{objectId}` is
//! unique in the context of the NMS box (spec §5.3.1.1). The host keeps the
//! mapping `objectId ↔ local id` in its own store, exposed through the
//! [`MessageStorage`](crate::ports::MessageStorage) port.

use std::fmt;

use serde::{Deserialize, Serialize};

/// NMS object ID — unique in the context of the NMS box (spec §5.3.1.1).
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ObjectId(String);

impl ObjectId {
    pub fn new(id: impl Into<String>) -> Self {
        ObjectId(id.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Extracts the object ID from an object resource URL: it is the last path
    /// segment of `.../objects/{objectId}` (spec §5.3.1.1).
    pub fn from_resource_url(url: &str) -> Option<Self> {
        let seg = url.rsplit('/').next()?;
        if seg.is_empty() {
            None
        } else {
            Some(ObjectId(seg.to_owned()))
        }
    }
}

impl fmt::Display for ObjectId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Host-local message ID (e.g. a row ID in the integrator's SQLite store).
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct LocalId(String);

impl LocalId {
    pub fn new(id: impl Into<String>) -> Self {
        LocalId(id.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for LocalId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// One `objectId ↔ local id` association (ADR D3).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ObjectMapping {
    pub object_id: ObjectId,
    pub local_id: LocalId,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn object_id_from_resource_url() {
        // Resource URL form of spec §5.3.1.1.
        assert_eq!(
            ObjectId::from_resource_url(
                "http://example.org/nms/v1/base/tel:+12125551212/objects/abcdef12345678"
            )
            .as_ref()
            .map(ObjectId::as_str),
            Some("abcdef12345678")
        );
        assert_eq!(ObjectId::from_resource_url("http://x/objects/"), None);
    }

    #[test]
    fn mapping_round_trip() {
        let m = ObjectMapping {
            object_id: ObjectId::new("obj542"),
            local_id: LocalId::new("row-42"),
        };
        let v = serde_json::to_value(&m).unwrap();
        assert_eq!(
            serde_json::from_value::<ObjectMapping>(v.clone()).unwrap(),
            m
        );
        assert_eq!(m.object_id.to_string(), "obj542");
    }
}
