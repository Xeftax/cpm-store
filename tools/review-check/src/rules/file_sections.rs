//! Règle `file-sections` : un fichier .rs avec plus de 10 items et AUCUNE bannière
//! de section (`// ==== ... ====`) manque d'organisation thématique -> découper
//! en sections (déclaration / constructeurs / lookup / accesseurs / serde / tests).

use super::{Candidate, Rule};

const MAX_ITEMS_WITHOUT_SECTIONS: usize = 10;

pub struct FileSections;

impl Rule for FileSections {
    fn id(&self) -> &'static str {
        "file-sections"
    }

    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate> {
        let has_sections = src.lines().any(|l| l.trim_start().starts_with("// ="));
        let violation = ast.items.len() > MAX_ITEMS_WITHOUT_SECTIONS && !has_sections;
        vec![Candidate { line: 1, violation }]
    }
}
