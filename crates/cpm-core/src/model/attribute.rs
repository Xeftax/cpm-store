//! Object/folder attributes.
//!
//! `Attribute` / `AttributeList` per REST-NMS §5.3.2.5 / §5.3.2.6. Attribute
//! names are **case-insensitive** (REST-NMS §5.3.2.5). The RCS object attribute
//! names (Date, Message-Context, Direction, From, To, ...) are listed in
//! REST-NMS Appendix I "RCS Object Attributes Table"; CPM populates them per
//! the mapping table of spec §5.3.1.2.

use serde::{Deserialize, Serialize};
use std::ops::Deref;

use super::kind::{Direction, MessageContext};

// ===========================================================================
// Attribute — REST-NMS §5.3.2.5 "Type: Attribute"
// ===========================================================================

/// Individual attribute — REST-NMS §5.3.2.5 "Type: Attribute".
///
/// JSON shape: `{"name": "Subject", "value": ["..."]}`. Values are unencoded
/// Unicode strings (REST-NMS §5.3.2.5). `value` may arrive as a single string
/// or an array (XML-to-JSON rules of [REST_NetAPI_Common]) — hence
/// `one_or_many` directly on the field, no manual impl needed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attribute {
    pub name: String,
    #[serde(default, deserialize_with = "super::one_or_many")]
    pub value: Vec<String>,
}

impl Attribute {
    pub fn new(name: impl Into<String>, value: Vec<String>) -> Self {
        Attribute {
            name: name.into(),
            value,
        }
    }
}

// ===========================================================================
// AttributeList — REST-NMS §5.3.2.6 "Type: AttributeList"
// ===========================================================================

/// Attribute list — REST-NMS §5.3.2.6 "Type: AttributeList".
///
/// JSON shape: `{"attribute": [{"name": ..., "value": [...]}, ...]}`.
/// Attribute names within the list MUST be unique (REST-NMS §5.3.2.6).
///
/// Named struct (not a newtype): the serde derive alone produces the `"attribute"`
/// key, no manual impl. `Deref<Target = Vec<Attribute>>` generates
/// `len()/iter()/is_empty()/...` — deliberately NO `DerefMut`, so `push` cannot
/// be exposed and violate name uniqueness (§5.3.2.6).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AttributeList {
    #[serde(default, deserialize_with = "super::one_or_many")]
    attribute: Vec<Attribute>,
}

// ---------------------------------------------------------------------------
// Construction: From (idiomatic conversion, .into()) + new (explicit call)
// ---------------------------------------------------------------------------

impl From<Vec<Attribute>> for AttributeList {
    fn from(v: Vec<Attribute>) -> Self {
        Self { attribute: v }
    }
}

impl AttributeList {
    pub fn new(attribute: Vec<Attribute>) -> Self {
        Self::from(attribute)
    }
}

// Read-only Deref: generates len()/iter()/is_empty()/get()... from Vec.
impl Deref for AttributeList {
    type Target = Vec<Attribute>;
    fn deref(&self) -> &Self::Target {
        &self.attribute
    }
}

// ---------------------------------------------------------------------------
// 1. Generic lookup — case-insensitive (REST-NMS §5.3.2.5)
// ---------------------------------------------------------------------------

impl AttributeList {
    /// Case-insensitive attribute lookup ("Message-ID" == "message-id", §5.3.2.5).
    pub fn get(&self, name: &str) -> Option<&Attribute> {
        self.iter()
            .find(|a: &&Attribute| a.name.eq_ignore_ascii_case(name))
    }

    /// Values of a case-insensitive lookup.
    pub fn values(&self, name: &str) -> Option<&[String]> {
        self.get(name).map(|a: &Attribute| a.value.as_slice())
    }

    /// First value of an attribute, if present.
    pub fn first_value(&self, name: &str) -> Option<&str> {
        self.values(name)
            .and_then(|v: &[String]| v.first())
            .map(String::as_str)
    }
}

// ---------------------------------------------------------------------------
// 2. Typed accessors (Appendix I) — a single pattern, macro-generated
// ---------------------------------------------------------------------------

macro_rules! typed_attribute {
    ($(#[$meta:meta])* $method:ident, $name:literal, $ty:ty) => {
        $(#[$meta])*
        pub fn $method(&self) -> Option<$ty> {
            self.first_value($name).map(<$ty>::parse)
        }
    };
}

impl AttributeList {
    typed_attribute! {
        /// The `Message-Context` attribute (REST-NMS Appendix I; case-insensitive
        /// enumeration, profiles may define other values).
        message_context, "Message-Context", MessageContext
    }
    typed_attribute! {
        /// The `Direction` attribute (REST-NMS Appendix I: "In" / "Out").
        direction, "Direction", Direction
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attribute_names_are_case_insensitive() {
        // REST-NMS §5.3.2.5.
        let list = AttributeList::from(vec![Attribute::new(
            "Message-ID",
            vec!["abc@example.com".to_owned()],
        )]);
        assert!(list.get("message-id").is_some());
        assert_eq!(list.first_value("MESSAGE-ID"), Some("abc@example.com"));
    }

    #[test]
    fn attribute_list_json_shape() {
        // JSON shape of REST-NMS §5.3.2.6: {"attribute": [...]}.
        let list = AttributeList::from(vec![Attribute::new("Subject", vec!["hi".to_owned()])]);
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
        // XML-to-JSON rules of [REST_NetAPI_Common] produce a bare value for a
        // single repeated element.
        let v = serde_json::json!({"attribute": {"name": "Date", "value": "2014-02-01T14:30:30Z"}});
        let list: AttributeList = serde_json::from_value(v).unwrap();
        assert_eq!(list.first_value("date"), Some("2014-02-01T14:30:30Z"));
    }

    #[test]
    fn typed_accessors() {
        let list = AttributeList::from(vec![
            Attribute::new("Message-Context", vec!["multimedia-message".to_owned()]),
            Attribute::new("Direction", vec!["IN".to_owned()]),
        ]);
        assert_eq!(
            list.message_context(),
            Some(MessageContext::MultimediaMessage)
        );
        assert_eq!(list.direction(), Some(Direction::In));
    }

    #[test]
    fn deref_generates_vec_api() {
        let list = AttributeList::from(vec![
            Attribute::new("a", vec!["1".to_owned()]),
            Attribute::new("b", vec!["2".to_owned()]),
        ]);
        // Vec methods available without writing them by hand:
        assert_eq!(list.len(), 2);
        assert!(!list.is_empty());
        assert_eq!(list.iter().count(), 2);
    }
}
