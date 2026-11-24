//! Case-conversion rules mirroring `serde_derive`'s `RenameRule`
//! (`serde_derive/src/internals/case.rs`), extended with an acronym dictionary:
//! a word whose uppercase form appears in `acronyms` is emitted verbatim, so
//! `resource_url` becomes `resourceURL` under camelCase instead of serde's
//! plain `resourceUrl`.
//!
//! `apply_plain` is byte-exact with serde (same algorithms); `apply_acronyms`
//! only differs for the capitalizing rules (PascalCase / camelCase) and returns
//! `apply_plain` unchanged for the other rules, where an acronym word is
//! already fully uppercased or lowercased by the rule itself.

// ==== RenameRule ====

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RenameRule {
    Lowercase,
    Uppercase,
    PascalCase,
    CamelCase,
    SnakeCase,
    ScreamingSnakeCase,
    KebabCase,
    ScreamingKebabCase,
}

// ==== RenameRule implementation (serde-exact + acronym-aware) ====

impl RenameRule {
    /// Parses one of serde's eight `rename_all` rule names.
    pub fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "lowercase" => Self::Lowercase,
            "UPPERCASE" => Self::Uppercase,
            "PascalCase" => Self::PascalCase,
            "camelCase" => Self::CamelCase,
            "snake_case" => Self::SnakeCase,
            "SCREAMING_SNAKE_CASE" => Self::ScreamingSnakeCase,
            "kebab-case" => Self::KebabCase,
            "SCREAMING-KEBAB-CASE" => Self::ScreamingKebabCase,
            _ => return None,
        })
    }

    // ==== Rule application: apply_plain (serde-exact) + apply_acronyms ====

    /// serde's exact rename of `id` (fields are snake_case idents, variants
    /// PascalCase idents — same convention as serde_derive).
    pub fn apply_plain(self, id: &str, is_variant: bool) -> String {
        match self {
            Self::Lowercase => id.to_lowercase(),
            Self::Uppercase => id.to_uppercase(),
            Self::PascalCase => id.split('_').map(capitalize).collect(),
            Self::CamelCase => {
                if is_variant {
                    let pascal: String = id.split('_').map(capitalize).collect();
                    lower_first(pascal)
                } else {
                    id.split('_')
                        .enumerate()
                        .map(
                            |(i, w): (usize, &str)| {
                                if i == 0 { w.to_string() } else { capitalize(w) }
                            },
                        )
                        .collect()
                }
            }
            Self::SnakeCase => to_snake(id),
            Self::ScreamingSnakeCase => to_snake(id).to_uppercase(),
            Self::KebabCase => to_snake(id).replace('_', "-"),
            Self::ScreamingKebabCase => to_snake(id).to_uppercase().replace('_', "-"),
        }
    }

    /// Acronym-aware rename. Returns the same value as `apply_plain` unless a
    /// word of `id` matches the acronym dictionary (case-insensitively) and the
    /// rule capitalizes words.
    pub fn apply_acronyms(self, id: &str, is_variant: bool, acronyms: &[String]) -> String {
        if acronyms.is_empty() || !matches!(self, Self::PascalCase | Self::CamelCase) {
            return self.apply_plain(id, is_variant);
        }
        let mapped: Vec<String> = words_of(id)
            .iter()
            .map(|w: &String| {
                match acronyms
                    .iter()
                    .find(|a: &&String| a.eq_ignore_ascii_case(w))
                {
                    Some(a) => (*a).clone(),
                    None => w.clone(),
                }
            })
            .collect();
        match self {
            Self::PascalCase => mapped.iter().map(|w: &String| capitalize(w)).collect(),
            Self::CamelCase if is_variant => {
                let pascal: String = mapped.iter().map(|w: &String| capitalize(w)).collect();
                lower_first(pascal)
            }
            Self::CamelCase => {
                let mut it = mapped.iter();
                match it.next() {
                    Some(first) => {
                        first.clone() + &it.map(|w: &String| capitalize(w)).collect::<String>()
                    }
                    None => String::new(),
                }
            }
            _ => self.apply_plain(id, is_variant),
        }
    }
}

// ==== Word splitting (acronym-aware, same boundaries as serde's snake_case) ====

/// Splits an ident into lowercase words: `resource_url` -> ["resource", "url"],
/// `NotifyURL` -> ["notify", "url"] (the `URL` acronym is one word).
fn words_of(id: &str) -> Vec<String> {
    to_snake(id).split('_').map(str::to_string).collect()
}

/// serde-style camel/Pascal -> snake_case (acronym aware): "DeletedObject" ->
/// "deleted_object", "resourceURL" -> "resource_url".
fn to_snake(id: &str) -> String {
    let chars: Vec<char> = id.chars().collect();
    let mut out = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if c.is_uppercase() && i > 0 {
            let prev = chars[i - 1];
            let next_lower = chars
                .get(i + 1)
                .map(|n: &char| n.is_lowercase())
                .unwrap_or(false);
            if prev.is_lowercase() || prev.is_ascii_digit() || (prev.is_uppercase() && next_lower) {
                out.push('_');
            }
        }
        out.extend(c.to_lowercase());
    }
    out
}

// ==== Small string helpers ====

fn capitalize(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(f) => f.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

fn lower_first(word: String) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(f) => f.to_lowercase().collect::<String>() + chars.as_str(),
        None => word,
    }
}

// ==== Tests ====

#[cfg(test)]
mod tests {
    use super::{RenameRule, to_snake};

    #[test]
    fn plain_rules_match_serde() {
        let camel = RenameRule::CamelCase;
        assert_eq!(camel.apply_plain("resource_url", false), "resourceUrl");
        assert_eq!(camel.apply_plain("last_mod_seq", false), "lastModSeq");
        assert_eq!(camel.apply_plain("ChangedObject", true), "changedObject");
        assert_eq!(
            RenameRule::PascalCase.apply_plain("resource_url", false),
            "ResourceUrl"
        );
        assert_eq!(
            RenameRule::SnakeCase.apply_plain("ResourceURL", false),
            "resource_url"
        );
        assert_eq!(to_snake("NotifyURL"), "notify_url");
    }

    #[test]
    fn acronym_dictionary_keeps_full_caps() {
        let acronyms = vec!["URL".to_string()];
        let camel = RenameRule::CamelCase;
        assert_eq!(
            camel.apply_acronyms("resource_url", false, &acronyms),
            "resourceURL"
        );
        assert_eq!(
            camel.apply_acronyms("notify_url", false, &acronyms),
            "notifyURL"
        );
        assert_eq!(
            camel.apply_acronyms("payload_url", false, &acronyms),
            "payloadURL"
        );
        // No acronym word -> identical to serde's plain output.
        assert_eq!(
            camel.apply_acronyms("last_mod_seq", false, &acronyms),
            "lastModSeq"
        );
        // Non-capitalizing rules are untouched by the dictionary.
        assert_eq!(
            RenameRule::SnakeCase.apply_acronyms("resource_url", false, &acronyms),
            "resource_url"
        );
    }

    #[test]
    fn acronym_first_word_is_verbatim() {
        let acronyms = vec!["URL".to_string()];
        assert_eq!(
            RenameRule::CamelCase.apply_acronyms("url_path", false, &acronyms),
            "URLPath"
        );
    }
}
