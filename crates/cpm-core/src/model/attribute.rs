//! Object/folder attributes.
//!
//! `Attribute` / `AttributeList` per REST-NMS §5.3.2.5 / §5.3.2.6. Attribute
//! names are **case-insensitive** (REST-NMS §5.3.2.5). The RCS object attribute
//! names (Date, Message-Context, Direction, From, To, ...) are listed in
//! REST-NMS Appendix I "RCS Object Attributes Table"; CPM populates them per
//! the mapping table of spec §5.3.1.2.

use serde::{Deserialize, Deserializer, Serialize, Serializer};

use super::kind::{Direction, MessageContext};

/// Individual attribute — REST-NMS §5.3.2.5 "Type: Attribute".
///
/// JSON shape: `{"name": "Subject", "value": ["..."]}`. Values are unencoded
/// Unicode strings (REST-NMS §5.3.2.5).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Attribute {
    pub name: String,
    pub value: Vec<String>,
}

impl<'de> Deserialize<'de> for Attribute {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        struct Helper {
            name: String,
            #[serde(default, deserialize_with = "super::one_or_many")]
            value: Vec<String>,
        }
        let h = Helper::deserialize(deserializer)?;
        Ok(Attribute {
            name: h.name,
            value: h.value,
        })
    }
}

impl Attribute {
    pub fn new(name: impl Into<String>, value: Vec<String>) -> Self {
        Attribute {
            name: name.into(),
            value,
        }
    }
}

/// `AttributeList` — REST-NMS §5.3.2.6 "Type: AttributeList".
///
/// JSON shape: `{"attribute": [{"name": ..., "value": [...]}, ...]}`.
/// Attribute names within the list MUST be unique (REST-NMS §5.3.2.6).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AttributeList(pub Vec<Attribute>);

impl AttributeList {
    pub fn new() -> Self {
        Self(Vec::new())
    }

    /// Case-insensitive attribute lookup (REST-NMS §5.3.2.5: "Message-ID",
    /// "Message-Id" and "message-id" all refer to the same attribute).
    pub fn get(&self, name: &str) -> Option<&Attribute> {
        self.0.iter().find(|a| a.name.eq_ignore_ascii_case(name))
    }

    /// Values of a case-insensitive attribute lookup.
    pub fn values(&self, name: &str) -> Option<&[String]> {
        self.get(name).map(|a| a.value.as_slice())
    }

    /// First value of an attribute, if present.
    pub fn first_value(&self, name: &str) -> Option<&str> {
        self.values(name)
            .and_then(|v| v.first())
            .map(String::as_str)
    }

    /// The `Message-Context` attribute (REST-NMS Appendix I; case-insensitive
    /// enumeration, profiles may define other values).
    pub fn message_context(&self) -> Option<MessageContext> {
        self.first_value("Message-Context")
            .map(MessageContext::parse)
    }

    /// The `Direction` attribute (REST-NMS Appendix I: "In" / "Out").
    pub fn direction(&self) -> Option<Direction> {
        self.first_value("Direction").map(Direction::parse)
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn iter(&self) -> impl Iterator<Item = &Attribute> {
        self.0.iter()
    }
}

impl Serialize for AttributeList {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        let mut map = serializer.serialize_map(Some(1))?;
        map.serialize_entry("attribute", &self.0)?;
        map.end()
    }
}

impl<'de> Deserialize<'de> for AttributeList {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        struct Helper {
            #[serde(default, deserialize_with = "super::one_or_many")]
            attribute: Vec<Attribute>,
        }
        Ok(AttributeList(Helper::deserialize(deserializer)?.attribute))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attribute_names_are_case_insensitive() {
        // REST-NMS §5.3.2.5.
        let list = AttributeList(vec![Attribute::new(
            "Message-ID",
            vec!["abc@example.com".to_owned()],
        )]);
        assert!(list.get("message-id").is_some());
        assert_eq!(list.first_value("MESSAGE-ID"), Some("abc@example.com"));
    }

    #[test]
    fn attribute_list_json_shape() {
        // JSON shape of REST-NMS §5.3.2.6: {"attribute": [...]}.
        let list = AttributeList(vec![Attribute::new("Subject", vec!["hi".to_owned()])]);
        let v = serde_json::to_value(&list).unwrap();
        assert_eq!(
            v,
            serde_json::json!({"attribute": [{"name": "Subject", "value": ["hi"]}]})
        );
        let back: AttributeList = serde_json::from_value(v).unwrap();
        assert_eq!(back, list);
    }

    #[test]
    fn tolerates_single_value_instead_of_array() {
        // XML-to-JSON rules of [REST_NetAPI_Common] produce a bare string for a
        // single repeated element.
        let v = serde_json::json!({"attribute": {"name": "Date", "value": "2014-02-01T14:30:30Z"}});
        let list: AttributeList = serde_json::from_value(v).unwrap();
        assert_eq!(list.first_value("date"), Some("2014-02-01T14:30:30Z"));
    }

    #[test]
    fn typed_accessors() {
        let list = AttributeList(vec![
            Attribute::new("Message-Context", vec!["multimedia-message".to_owned()]),
            Attribute::new("Direction", vec!["IN".to_owned()]),
        ]);
        assert_eq!(
            list.message_context(),
            Some(MessageContext::MultimediaMessage)
        );
        assert_eq!(list.direction(), Some(Direction::In));
    }
}
