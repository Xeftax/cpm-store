---
name: model-struct-owner
description: "OWNER déclarations de types du domain model cpm-core (struct/enum, visibilité pub, derives, champs, factorisation de méthodes répétitives par macro_rules!, organisation en sections). NE JAMAIS exécuter en direct : quand pertinent, spawn un subagent (Vibe: agents.spawn, instructions = ce fichier). Trigger when adding/editing/reviewing a struct or enum in crates/cpm-core/src/model/**, or when 2+ methods share the same body up to a name/type. MUST BE USED before and after any PR touching model type declarations."
user-invocable: false
---

# model-struct-owner

Owner du domaine « déclarations de types du domain model » (cpm-core). Cas d'école :
PR #3, `crates/cpm-core/src/model/attribute.rs` (`Attribute`, `AttributeList`).

## Rôle dual

- **Advise BEFORE** : « je déclare un nouveau type » → quels derives, quelle visibilité, quels champs.
- **Review AFTER** : « review ce diff de déclarations » → verdict contre les invariants.

## Read first (à chaque invocation, jamais de mémoire)

- `crates/cpm-core/src/model/*.rs` (attribute.rs, kind.rs, folder.rs, mod.rs)
- `crates/cpm-core/src/model/mod.rs` pour les `pub use` (ré-exports)

## Invariants — Do & Don't

- DO dériver `Debug, Clone, PartialEq, Eq` ensemble sur les types de données.
- DON'T dériver `Eq` si un champ est `f32`/`f64` (`PartialEq` seul — `NaN != NaN`).
- DO des champs **possédés** uniquement (`String`, `Vec<String>`, `u64`...) : jamais de `&str`
  dans une struct du domaine, sinon il faut une lifetime sur la struct (`struct Emprunte<'a>`).
- DO `pub` au minimum nécessaire ; ré-exporter dans `mod.rs` via `pub use` plutôt que de rendre
  les sous-modules eux-mêmes publics quand ce n'est pas utile.
- Lifetimes : le paramètre d'un trait (ex. `'de` sur `Deserialize<'de>`) est **obligatoire dans
  l'impl** s'il est déclaré sur le trait (erreur E0726 sinon). `'static` = littéraux. Les
  lifetimes sont vérifiées à la compilation (borrow checker) et effacées à l'exécution.
- DO documenter la forme JSON attendue en commentaire doc (`///`) au-dessus de chaque type,
  avec la section de spec (REST-NMS / CPM-REST).

### règle newtype : nom sémantique + véhicule d'impls (orphan rule)

- Un newtype = `struct X(Vec<T>)` (tuple struct, champ `.0`). Il sert à donner un nom à un type
  existant ET à y implémenter des traits étrangers : `impl Serialize for Vec<Attribute>` est
  interdit (E0117, orphan rule — trait et type étrangers), `impl Serialize for AttributeList`
  est autorisé car `AttributeList` est local. C'est pourquoi la PR #3 écrit l'enveloppe
  `{"attribute": [...]}` à la main.
- Choisir newtype vs struct nommée pour le mapping JSON, en connaissance de cause :
  - **struct nommée + derive + Deref = meilleur des deux mondes** quand le JSON a une clé nommée :
    `struct AttributeList { #[serde(default, deserialize_with = "super::one_or_many")] attribute: Vec<Attribute> }`
    → le derive produit `{"attribute": [...]}` tout seul (prouvé avec cargo/serde : serialize,
    deserialize, champ absent → vec vide) + `impl Deref<Target = Vec<Attribute>>` génère
    `len()/iter()/is_empty()`, champ privé. Plus d'impl serde manuel.
  - newtype `X(pub Vec<T>)` : construction tuple pratique (`X(vec![...])`), mais derive
    **transparent** (sérialise `[...]` sans clé) → impl serde manuel pour l'enveloppe. Cas PR #3
    (`AttributeList(pub Vec<Attribute>)` + impl manuel lignes 103-121).
- DO documenter ce choix dans le commentaire doc du type.

### règle d'exposition du contenu d'un newtype

- DO `impl std::ops::Deref<Target = Vec<T>>` si on veut **toute** l'API de la collection
  (`len()`, `iter()`, `is_empty()`, `get()`...) **générée automatiquement** — champ privé en
  prime. Preuve compilée : ex13. Caveat : Deref expose aussi `push/remove/clear` — à éviter si
  un invariant doit être protégé (ex. unicité des noms §5.3.2.6).
- DON'T écrire à la main des pures délégations (`len/iter/is_empty`) quand `Deref` les génère —
  c'est de la duplication morte. N'écrire à la main que les méthodes **métier** (ex. `get`
  case-insensitive §5.3.2.5).
- Si on filtre l'API (invariant à l'insertion) : champ privé + méthodes choisies, SANS Deref.
- Champ `pub .0` = transparence totale assumée (les appelants font `x.0.len()`) — acceptable
  mais moins lisible que `x.len()` via Deref.
- DO `impl From<Vec<T>> for X` (+ `new`) pour garder la construction ergonomique avec une struct
  nommée : `X::from(vec![...])` ou `vec![...].into()` (prouvé, ex16).
- **Deref est tout-ou-rien** : `type Target` est un type concret, la deref coercion expose TOUTES
  ses méthodes publiques — impossible de passer une liste de noms. Pour un sous-ensemble
  explicite : méthodes à la main si peu nombreuses, sinon macro `delegate! { len -> usize, is_empty -> bool }` (liste explicite + génération, prouvé ex17 — `push` reste indisponible,
  E0599), ou crate `ambassador` (`#[derive(Delegate)]` sur un trait) pour du déclaratif lourd.

### règle d'organisation : un fichier de type = sections thématiques

- DO découper un fichier de type en sections commentées : déclaration / lookup générique /
  accesseurs spec / (dé)sérialisation. Cas PR #3 : refactor d'`AttributeList` en 3 sections.
  (Notion distincte de la factorisation de méthodes ci-dessous.)

### règle de factorisation : méthodes dupliquées → génération

- RÈGLE : 2+ méthodes avec exactement le même corps à un nom/type près → générer par
  `macro_rules!` déclarative plutôt que copier-coller. Cas PR #3 : `message_context()` /
  `direction()` = toutes deux `first_value(NOM).map(T::parse)` → macro `typed_attribute!`
  (2 lignes de déclaration par attribut, doc comment conservé).
- La macro vit dans le fichier du type (un seul point d'entrée) ; on ne la monte dans `mod.rs`
  que si elle est réutilisée par un autre module.
- Alternative si 10+ cas : un trait `SpecAttribute { const NAME: &'static str; fn parse(&str) -> Self; }`
  - `fn typed<V: SpecAttribute>(&self) -> Option<V>`. Pour 2-3 cas, la macro gagne (méthodes
    nommées, discoverables, doc comments) — ne pas over-engineer.

## Rapport

- Citer `file:line` lus pendant cette invocation. Verdict en deux parties : **prouvé**
  (commande + sortie) / **non prouvé** (et pourquoi).
