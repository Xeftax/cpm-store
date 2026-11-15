---
name: review-memory-owner
description: "OWNER de la mémoire de review de cpm-store (known-patterns : quoi noter, quelle sévérité, index des occurrences, hygiène du mécanisme). NE JAMAIS exécuter en direct : quand pertinent, spawn un subagent (Vibe: agents.spawn, instructions = ce fichier). Trigger when adding/changing a rule in .vibe/review/known-patterns.toml or the check script, or when a review comment reveals a new anti-pattern. MUST BE USED before setting any severity above warning and before indexing occurrences."
user-invocable: false
---

# review-memory-owner

Owner du domaine « mémoire de review » : transformer les commentaires de PR passés en
règles exécutables (known-patterns), sans bruit ni faux positifs. Cas d'école : PR #3
(commentaires sur `attribute.rs` lignes 23/40/53 + récap) + council du 2026-11-14
(5 advisors + 5 peer-reviews + chairman).

## Rôle dual

- **Advise BEFORE** : « on a trouvé un anti-pattern » → quelle règle, quelle sévérité, quelles occurrences indexer.
- **Review AFTER** : verdict contre les invariants.

## Read first (à chaque invocation, jamais de mémoire)

- `.vibe/review/known-patterns.toml` (quand il existe) + `scripts/review/check-known-patterns.sh`
- Les skills-owners de domaine : `model-struct-owner`, `serde-mapping-owner`, `constructor-owner`
- `docs/planning/review-strategy.md` (doc-station) — la pratique déterministe de référence

## Invariants — Do & Don't

### quoi noter, et quand

- DO noter un anti-pattern **dès la 1ère occurrence** — rien n'empêche qu'il se représente.
  (Seuil « signalé 2 fois » rejeté : la récurrence n'est pas un prérequis à la documentation.)
- **ON NE SUPPRIME JAMAIS UNE RÈGLE.** Si elle ne marche plus : on l'édite/adapte (regex, scope),
  ou on l'exclut par fichier via `exclude_files = [...]` dans le pattern (équivalent des
  `#[allow(...)]` de lint), ou au pire soupape par ligne `// review: ignore <rule-id>`.
  Une règle retirée du TOML perd son historique d'occurrences.
- DO restreindre le `scope` à un seul fichier pendant une review progressive (ex. attribute.rs
  d'abord, kind.rs ensuite) plutôt que de tout scope d'un coup et noyer de faux positifs.
- **Un fichier ne va dans `exclude_files` qu'avec l'accord explicite de l'utilisateur.**
  Par défaut on garde les warnings : ils disparaissent quand la règle ou les fichiers sont
  fixés, pas en les cachant.
- DO indexer **toutes les occurrences** (fichier:ligne ou commit de première apparition), pas ce
  qui l'a remplacé : si la règle est modifiée/supprimée un jour, on doit pouvoir lister d'un coup
  toutes les parties du code concernées et vérifier que le changement de règle est justifiable
  partout, puis adapter chaque endroit à la nouvelle règle.
- DON'T capitaliser les one-offs comme des gates (voir sévérité).

### sévérité

- DO `severity = "warning"` pour **tout** pattern de style/design.
- DON'T de hard gate sur un pattern de style : le reviewer est un LLM qui lit **tous** les
  warnings (et peut faire des passes dédiées « regarde tous les warnings / fix-les tous »),
  alors qu'un humain ignorerait les warnings. Imposer bloque et freine sans gain.
- DO réserver le **bloquant au fonctionnel uniquement** : compilateur, tests, `clippy -D`.
  C'est déjà couvert ailleurs — ne pas le dupliquer dans known-patterns.

### hygiène du mécanisme

- DO lancer le check sur le **diff de la PR**, pas le fichier entier (sinon re-flag de patterns
  déjà corrigés = bruit).
- DO prévoir une soupape `// review: ignore <rule-id>` (sinon la gate finit contournée en bloc
  → faux négatif silencieux).
- DO péremption : une règle jamais hit depuis N reviews est archivée, pas supprimée aveuglément.
- DO mesurer d'abord : grep rétrospectif des patterns sur **tout l'historique git**
  (`git log -p --all | grep -E <pattern>`) avant de figer quoi que ce soit — la métrique de
  récurrence réelle. (Fait pour la PR #3 : `one_or_many` = 15 ajouts/9 fichiers → classe
  récurrente ; `struct Helper` = 2 → one-off.)
- DON'T d'embeddings/RAG à ce stade (corpus trop petit → bruit). LLM résiduel uniquement si un
  pattern sémantique est **prouvé manqué 2 fois** par le grep.
- DO lancer le check sur tout le repo une fois pour vérifier qu'il ne crie pas sur du code sain.

### format de known-patterns.toml

```toml
[[pattern]]
id = "serde-helper-identity"          # kebab-case, stable (référencé par review: ignore)
scope = "crates/**/*.rs"               # glob du check
regex = "struct Helper"                # pattern déterministe (grep -E), pas de sémantique
message = "impl Deserialize manuel + Helper : si la conversion est une recopie identité, poser #[serde(...)] sur le champ — voir serde-mapping-owner"
severity = "warning"                   # toujours warning (voir invariants)
occurrences = [                        # TOUTES les occurrences, jamais le remplaçant
  { file = "crates/cpm-core/src/model/attribute.rs", lines = "26-37", since = "PR #3" },
]
```

## Rapport

- Citer `file:line` lus pendant cette invocation. Verdict en deux parties : **prouvé**
  (commande + sortie) / **non prouvé** (et pourquoi).
