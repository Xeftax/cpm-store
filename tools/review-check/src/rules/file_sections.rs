//! Rule `file-sections`: a .rs file with more than 10 items and NO section
//! banner (`// ==== ... ====`) lacks organization -> cut it into
//! sections (declarations / constructors / lookup / accessors / serde / tests).

use super::{Candidate, Rule};

const MAX_ITEMS_WITHOUT_SECTIONS: usize = 10;

pub struct FileSections;

impl Rule for FileSections {
    fn id(&self) -> &'static str {
        "file-sections"
    }

    fn candidates(&self, ast: &syn::File, src: &str) -> Vec<Candidate> {
        let has_sections = src.lines().any(super::is_section_banner);
        let violation = ast.items.len() > MAX_ITEMS_WITHOUT_SECTIONS && !has_sections;
        vec![Candidate { line: 1, violation }]
    }
}
