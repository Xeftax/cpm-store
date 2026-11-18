//! CPM object kinds and the typed attribute enumerations they derive from.
//!
//! - `MessageContext` is the `Message-Context` attribute enumeration of
//!   REST-NMS Appendix I (at least "voice-message", "video-message",
//!   "fax-message", "pager-message", "multimedia-message", "text-message",
//!   "none"; case-insensitive; profiles may define others). [CPM-REST] adds
//!   "chat-message" (annexes D/F), "file-message" (§5.3.2), "group-state-message"
//!   (annex G) and "imdn-message" (§5.3.10).
//! - `CpmObjectKind` classifies an [`NmsObject`](super::object::NmsObject) per
//!   the object kinds of spec §5.3.1–§5.3.10 and the non-CPM flag template of
//!   §5.3.9.2.

use std::borrow::Cow;

use serde::{Deserialize, Deserializer, Serialize, Serializer};

use super::attribute::AttributeList;
use super::flags::{FlagList, MetadataFlag};
use super::object::NmsObject;

// ==== MessageContext — REST-NMS Appendix I ====
/// Value of the `Message-Context` attribute (REST-NMS Appendix I; CPM-REST
/// §5.3.2/§5.3.10 and annexes C–H). Case-insensitive.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum MessageContext {
    VoiceMessage,
    VideoMessage,
    FaxMessage,
    /// SMS (REST-NMS Appendix I).
    PagerMessage,
    /// MMS (REST-NMS Appendix I).
    MultimediaMessage,
    /// Email (REST-NMS Appendix I).
    TextMessage,
    /// CPM chat message (CPM-REST annexes D/F).
    ChatMessage,
    /// File transfer history object — MUST be "file-message" (spec §5.3.2).
    FileMessage,
    /// Group state object (spec annex G).
    GroupStateMessage,
    /// IMDN object — MUST be "imdn-message" (spec §5.3.10).
    ImdnMessage,
    None,
    /// Profile-defined value (REST-NMS Appendix I: "Other values may be
    /// defined by profiles or other standards").
    Other(String),
}

impl MessageContext {
    pub fn as_str(&self) -> Cow<'_, str> {
        match self {
            Self::VoiceMessage => Cow::Borrowed("voice-message"),
            Self::VideoMessage => Cow::Borrowed("video-message"),
            Self::FaxMessage => Cow::Borrowed("fax-message"),
            Self::PagerMessage => Cow::Borrowed("pager-message"),
            Self::MultimediaMessage => Cow::Borrowed("multimedia-message"),
            Self::TextMessage => Cow::Borrowed("text-message"),
            Self::ChatMessage => Cow::Borrowed("chat-message"),
            Self::FileMessage => Cow::Borrowed("file-message"),
            Self::GroupStateMessage => Cow::Borrowed("group-state-message"),
            Self::ImdnMessage => Cow::Borrowed("imdn-message"),
            Self::None => Cow::Borrowed("none"),
            Self::Other(s) => Cow::Borrowed(s.as_str()),
        }
    }

    /// Case-insensitive parse (REST-NMS Appendix I: "This attribute is
    /// case-insensitive").
    pub fn parse(s: &str) -> Self {
        match s.to_ascii_lowercase().as_str() {
            "voice-message" => Self::VoiceMessage,
            "video-message" => Self::VideoMessage,
            "fax-message" => Self::FaxMessage,
            "pager-message" => Self::PagerMessage,
            "multimedia-message" => Self::MultimediaMessage,
            "text-message" => Self::TextMessage,
            "chat-message" => Self::ChatMessage,
            "file-message" => Self::FileMessage,
            "group-state-message" => Self::GroupStateMessage,
            "imdn-message" => Self::ImdnMessage,
            "none" => Self::None,
            _ => Self::Other(s.to_owned()),
        }
    }
}

// ---- Wire mapping (serde) : as_str / parse, case-insensitive (REST-NMS §5.3.2.4) ----
// review: ignore manual-serde-impl — enum a mapping custom de variantes (chaines wire via as_str/parse) ; un derive ne peut pas l'exprimer (voir known-patterns when_not_applicable)
impl Serialize for MessageContext {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.as_str())
    }
}

// review: ignore manual-serde-impl — idem : deserialisation via parse (variantes custom, REST-NMS Appendix I)
impl<'de> Deserialize<'de> for MessageContext {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        Ok(Self::parse(&s))
    }
}

// ==== Direction — REST-NMS Appendix I ====
/// Value of the `Direction` attribute (REST-NMS Appendix I: "In" for incoming
/// traffic, "Out" for traffic outgoing from the CPM User — mapping table of
/// spec §5.3.1.2). Case-insensitive in practice.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Direction {
    In,
    Out,
}

impl Direction {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::In => "In",
            Self::Out => "Out",
        }
    }

    pub fn parse(s: &str) -> Self {
        if s.eq_ignore_ascii_case("out") {
            Self::Out
        } else {
            Self::In
        }
    }
}

// ==== CpmObjectKind — classification des objets (spec §5.3) ====
/// The kind of a CPM storage object — spec §5.3.1 (message object), §5.3.2
/// (file transfer history), §5.3.3 (session info), §5.3.4 (group state),
/// §5.3.5 (stand-alone media), §5.3.9 (non-CPM objects, call log), §5.3.10
/// (IMDN).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CpmObjectKind {
    /// Message object (spec §5.3.1) — the default kind.
    Message,
    /// File transfer history object (spec §5.3.2).
    FileTransferHistory,
    /// Session info object (spec §5.3.3).
    SessionInfo,
    /// Group state object (spec §5.3.4).
    GroupState,
    /// Stand-alone media object (spec §5.3.5).
    StandaloneMedia,
    /// IMDN object, i.e. a disposition notification stored as a message object
    /// with no payload (spec §5.3.10).
    Imdn,
    /// Call log object (spec §5.3.9.3, flag `$CPM_CallLog_*` per §5.3.9.2).
    CallLog,
    /// Other non-CPM object (spec §5.3.9.2, any other `$CPM_*` flag).
    NonCpm,
    /// No normative marker over the REST binding.
    Unknown,
}

impl NmsObject {
    /// Classifies the object per spec §5.3.
    ///
    /// Normative markers available over the REST binding: the `Message-Context`
    /// attribute (file-message §5.3.2, imdn-message §5.3.10, group-state-message
    /// annex G) and the `$CPM_*` non-CPM flags (§5.3.9.2). Session info (§5.3.3)
    /// and stand-alone media (§5.3.5) objects carry no machine-readable marker
    /// in the REST binding and are reported as [`CpmObjectKind::Message`].
    pub fn cpm_kind(&self) -> CpmObjectKind {
        cpm_kind(&self.attributes, &self.flags)
    }
}

/// Classification logic shared by [`NmsObject::cpm_kind`].
pub(crate) fn cpm_kind(attributes: &AttributeList, flags: &FlagList) -> CpmObjectKind {
    // Non-CPM object flags take precedence: they identify the object without
    // opening it (spec §5.3.9.2).
    if flags.iter().any(|f| match f {
        MetadataFlag::Keyword(k) => k.to_ascii_lowercase().starts_with("$cpm_calllog"),
        _ => false,
    }) {
        return CpmObjectKind::CallLog;
    }
    if flags.has_cpm_prefixed_flag() {
        return CpmObjectKind::NonCpm;
    }
    match attributes.message_context() {
        Some(MessageContext::FileMessage) => CpmObjectKind::FileTransferHistory,
        Some(MessageContext::ImdnMessage) => CpmObjectKind::Imdn,
        Some(MessageContext::GroupStateMessage) => CpmObjectKind::GroupState,
        Some(_) | None => CpmObjectKind::Message,
    }
}

// ==== Tests ====
#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::attribute::Attribute;

    fn attrs(pairs: &[(&str, &str)]) -> AttributeList {
        AttributeList::from(
            pairs
                .iter()
                .map(|(n, v)| Attribute::new(*n, vec![(*v).to_owned()]))
                .collect::<Vec<_>>(),
        )
    }

    #[test]
    fn message_context_round_trip() {
        for wire in [
            "voice-message",
            "video-message",
            "fax-message",
            "pager-message",
            "multimedia-message",
            "text-message",
            "none",
            "chat-message",
            "file-message",
            "group-state-message",
            "imdn-message",
        ] {
            let mc = MessageContext::parse(wire);
            assert_eq!(mc.as_str(), wire);
            let json = serde_json::to_string(&mc).unwrap();
            assert_eq!(serde_json::from_str::<MessageContext>(&json).unwrap(), mc);
        }
        // Case-insensitive (REST-NMS Appendix I).
        assert_eq!(
            MessageContext::parse("Multimedia-Message"),
            MessageContext::MultimediaMessage
        );
        // Profile-defined value.
        assert_eq!(
            MessageContext::parse("custom-thing"),
            MessageContext::Other("custom-thing".to_owned())
        );
    }

    #[test]
    fn kind_from_message_context() {
        let empty = FlagList::new();
        assert_eq!(
            cpm_kind(&attrs(&[("Message-Context", "file-message")]), &empty),
            CpmObjectKind::FileTransferHistory
        );
        assert_eq!(
            cpm_kind(&attrs(&[("Message-Context", "imdn-message")]), &empty),
            CpmObjectKind::Imdn
        );
        assert_eq!(
            cpm_kind(
                &attrs(&[("Message-Context", "group-state-message")]),
                &empty
            ),
            CpmObjectKind::GroupState
        );
        assert_eq!(
            cpm_kind(&attrs(&[("Message-Context", "multimedia-message")]), &empty),
            CpmObjectKind::Message
        );
        assert_eq!(
            cpm_kind(&AttributeList::default(), &empty),
            CpmObjectKind::Message
        );
    }

    #[test]
    fn kind_from_non_cpm_flags() {
        // Non-CPM flag template "$CPM_*" (spec §5.3.9.2).
        let mut call_log = FlagList::new();
        call_log.insert(MetadataFlag::parse("$CPM_CallLog_EnCall"));
        assert_eq!(
            cpm_kind(&attrs(&[("Message-Context", "chat-message")]), &call_log),
            CpmObjectKind::CallLog
        );
        let mut vvm = FlagList::new();
        vvm.insert(MetadataFlag::parse("$CPM_VVM"));
        assert_eq!(
            cpm_kind(&AttributeList::default(), &vvm),
            CpmObjectKind::NonCpm
        );
    }
}
