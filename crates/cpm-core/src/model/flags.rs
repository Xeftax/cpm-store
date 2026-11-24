//! Metadata flags.
//!
//! Flags per spec §5.6 ([CPM-REST] "Metadata Structure"); the flag name strings
//! are defined by REST-NMS Appendix H "Flag Names Table" (normative) and §5.3.2.3
//! "Type: Flag". Flag names are **case-insensitive** (REST-NMS §5.3.2.4) and
//! deployments MAY support additional strings (REST-NMS Appendix H note), e.g.
//! the non-CPM object flags following the `$CPM_*` template of spec §5.3.9.2.

use std::borrow::Cow;
use std::collections::BTreeSet;
use std::fmt;
use std::ops::{Deref, DerefMut};

use serde::{Deserialize, Deserializer, Serialize, Serializer};

// ==== MetadataFlag — REST-NMS Appendix H "Flag Names Table" ====

/// A metadata flag associated with an object or folder (spec §5.6).
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum MetadataFlag {
    /// `\\Seen` — message has been read (spec §5.6).
    Seen,
    /// `\\Answered` — message has been answered (spec §5.6).
    Answered,
    /// `\\Flagged` — message is flagged for urgent/special attention (spec §5.6).
    Flagged,
    /// `\\Deleted` — marked for removal by a later EXPUNGE (spec §5.6).
    Deleted,
    /// `\\Draft` — composition not completed (spec §5.6).
    Draft,
    /// `\\Recent` — recently arrived in this mailbox (spec §5.6).
    Recent,
    /// `$MDNSent` — a disposition notification has been sent (REST-NMS Appendix H).
    MdnSent,
    /// `$Forwarded` — message has been forwarded (spec §5.6).
    Forwarded,
    /// `\\read-report-sent` — a read receipt has been sent (spec §5.6).
    ReadReportSent,
    /// `Archived` — message is archived (spec §5.6).
    Archived,
    /// Any other flag string, e.g. `$CPM_VVM` or `$CPM_CallLog_EnCall`
    /// (non-CPM object flag template, spec §5.3.9.2).
    Keyword(String),
}

// ---- Wire mapping : as_str / parse (case-insensitive, REST-NMS §5.3.2.4) ----

impl MetadataFlag {
    /// The flag name as sent on the wire (JSON string).
    pub fn as_str(&self) -> Cow<'_, str> {
        match self {
            Self::Seen => Cow::Borrowed("\\Seen"),
            Self::Answered => Cow::Borrowed("\\Answered"),
            Self::Flagged => Cow::Borrowed("\\Flagged"),
            Self::Deleted => Cow::Borrowed("\\Deleted"),
            Self::Draft => Cow::Borrowed("\\Draft"),
            Self::Recent => Cow::Borrowed("\\Recent"),
            Self::MdnSent => Cow::Borrowed("$MDNSent"),
            Self::Forwarded => Cow::Borrowed("$Forwarded"),
            Self::ReadReportSent => Cow::Borrowed("\\read-report-sent"),
            Self::Archived => Cow::Borrowed("Archived"),
            Self::Keyword(k) => Cow::Borrowed(k.as_str()),
        }
    }

    /// Parses a flag name, case-insensitively (REST-NMS §5.3.2.4). Leading
    /// backslashes are ignored so that `\\Seen` and `\\Seen` both map to `Seen`
    /// (the latter appears in extracted spec text).
    pub fn parse(name: &str) -> Self {
        match name.trim_start_matches('\\').to_ascii_lowercase().as_str() {
            "seen" => Self::Seen,
            "answered" => Self::Answered,
            "flagged" => Self::Flagged,
            "deleted" => Self::Deleted,
            "draft" => Self::Draft,
            "recent" => Self::Recent,
            "$mdnsent" => Self::MdnSent,
            "$forwarded" => Self::Forwarded,
            "read-report-sent" => Self::ReadReportSent,
            "archived" => Self::Archived,
            _ => Self::Keyword(name.to_owned()),
        }
    }
}

impl fmt::Display for MetadataFlag {
    // Display::fmt and Serialize::serialize both delegate to as_str() (two traits, not factorizable).
    // review: ignore duplicate-fn-bodies
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.as_str())
    }
}

// Enum with custom variant mapping (wire strings via as_str/parse,
// REST-NMS Appendix H): a derive cannot express it.
// review: ignore manual-serde-impl
impl Serialize for MetadataFlag {
    // review: ignore duplicate-fn-bodies — see Display above.
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.as_str())
    }
}

// review: ignore manual-serde-impl — same: deserialization via parse (custom variants).
impl<'de> Deserialize<'de> for MetadataFlag {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        Ok(Self::parse(&s))
    }
}

// ==== FlagList — REST-NMS §5.3.2.4 "Type: FlagList" ====

/// `FlagList` — REST-NMS §5.3.2.4 "Type: FlagList".
///
/// JSON shape: `{"flag": ["\\Seen", "\\Flagged"]}`. Duplicates are ignored and
/// order is not preserved (REST-NMS §5.3.2.4), hence the `BTreeSet`.
///
/// Named struct (not a newtype): the derive alone produces the `"flag"` key.
/// `Deref`/`DerefMut<Target = BTreeSet<MetadataFlag>>` generate
/// `contains/insert/remove/len/iter/is_empty/...` — no insertion invariant
/// to protect here (unlike `AttributeList`, REST-NMS §5.3.2.6), so
/// DerefMut is safe: the BTreeSet itself preserves uniqueness.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
pub struct FlagList {
    #[serde(default, deserialize_with = "super::one_or_many_set")]
    flag: BTreeSet<MetadataFlag>,
}

// ---- Construction: From (idiomatic conversion, .into()) + new (explicit call) ----

impl From<BTreeSet<MetadataFlag>> for FlagList {
    fn from(flag: BTreeSet<MetadataFlag>) -> Self {
        Self { flag }
    }
}

impl FlagList {
    pub fn new() -> Self {
        Self::default()
    }
}

impl FromIterator<MetadataFlag> for FlagList {
    fn from_iter<I: IntoIterator<Item = MetadataFlag>>(iter: I) -> Self {
        Self {
            flag: iter.into_iter().collect(),
        }
    }
}

// ---- Set access via Deref/DerefMut (generated API, no manual delegations) ----

impl Deref for FlagList {
    type Target = BTreeSet<MetadataFlag>;
    fn deref(&self) -> &Self::Target {
        &self.flag
    }
}

impl DerefMut for FlagList {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.flag
    }
}

// ---- Business logic ----

impl FlagList {
    /// True when the flag starts with the non-CPM object template prefix
    /// `$CPM_` (spec §5.3.9.2).
    pub fn has_cpm_prefixed_flag(&self) -> bool {
        self.flag
            .iter()
            .any(|f: &MetadataFlag| matches!(f, MetadataFlag::Keyword(k) if k.starts_with("$CPM_")))
    }
}

// ---- Serialization ----

// Serialize writes the flags sorted by wire name (REST-NMS §5.3.2.4: the order is
// not preserved); a derive would emit the BTreeSet Ord order of the variants,
// a transformation not expressible with serde attributes.
// review: ignore manual-serde-impl
impl Serialize for FlagList {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        let mut flags: Vec<&MetadataFlag> = self.flag.iter().collect();
        flags.sort_by_key(|f: &&MetadataFlag| f.as_str().into_owned());
        let mut map = serializer.serialize_map(Some(1))?;
        map.serialize_entry("flag", &flags)?;
        map.end()
    }
}

// ==== Tests ====

#[cfg(test)]
mod tests {
    use super::*;

    /// Every flag that spec §5.6 SHALL support must round-trip through its
    /// wire string (covers the "supported Flags" SCR of docs/conformance.md).
    #[test]
    fn all_spec_flags_round_trip() {
        let expected = [
            ("\\Seen", MetadataFlag::Seen),
            ("\\Answered", MetadataFlag::Answered),
            ("\\Flagged", MetadataFlag::Flagged),
            ("\\Deleted", MetadataFlag::Deleted),
            ("\\Draft", MetadataFlag::Draft),
            ("\\Recent", MetadataFlag::Recent),
            ("$Forwarded", MetadataFlag::Forwarded),
            ("\\read-report-sent", MetadataFlag::ReadReportSent),
            ("Archived", MetadataFlag::Archived),
            ("$MDNSent", MetadataFlag::MdnSent),
        ];
        for (wire, flag) in expected {
            assert_eq!(MetadataFlag::parse(wire), flag, "parse {wire}");
            assert_eq!(flag.as_str(), wire, "as_str {wire}");
            let json = serde_json::to_string(&flag).unwrap();
            assert_eq!(json, serde_json::to_string(wire).unwrap());
            let back: MetadataFlag = serde_json::from_str(&json).unwrap();
            assert_eq!(back, flag);
        }
    }

    #[test]
    fn flag_names_are_case_insensitive() {
        // Flag names are case-insensitive (REST-NMS §5.3.2.4).
        assert_eq!(MetadataFlag::parse("\\SEEN"), MetadataFlag::Seen);
        assert_eq!(MetadataFlag::parse("$forwarded"), MetadataFlag::Forwarded);
        assert_eq!(MetadataFlag::parse("ARCHIVED"), MetadataFlag::Archived);
    }

    #[test]
    fn non_cpm_template_flags_become_keywords() {
        // Non-CPM object flags follow the "$CPM_*" template (spec §5.3.9.2).
        assert_eq!(
            MetadataFlag::parse("$CPM_CallLog_EnCall"),
            MetadataFlag::Keyword("$CPM_CallLog_EnCall".to_owned())
        );
        let mut set = FlagList::new();
        set.insert(MetadataFlag::parse("$CPM_VVM"));
        assert!(set.has_cpm_prefixed_flag());
    }

    #[test]
    fn flag_list_json_shape() {
        // JSON shape of REST-NMS §5.3.2.4: {"flag": [...]}.
        let mut set = FlagList::new();
        set.insert(MetadataFlag::Seen);
        set.insert(MetadataFlag::Flagged);
        let v = serde_json::to_value(&set).unwrap();
        assert_eq!(v, serde_json::json!({"flag": ["\\Flagged", "\\Seen"]}));
        let back: FlagList = serde_json::from_value(v).unwrap();
        assert!(back.contains(&MetadataFlag::Seen));
        assert!(back.contains(&MetadataFlag::Flagged));
    }

    #[test]
    fn deref_generates_set_api() {
        let mut set = FlagList::from_iter([
            MetadataFlag::Seen,
            MetadataFlag::Flagged,
            MetadataFlag::Seen,
        ]);
        // BTreeSet methods available without writing them by hand:
        assert_eq!(set.len(), 2); // duplicate ignored (REST-NMS §5.3.2.4)
        assert!(!set.is_empty());
        assert!(set.contains(&MetadataFlag::Seen));
        assert!(set.remove(&MetadataFlag::Seen));
        assert!(!set.contains(&MetadataFlag::Seen));
        assert_eq!(set.iter().count(), 1);
    }
}
