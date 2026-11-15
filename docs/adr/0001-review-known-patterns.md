# ADR 0001 — Mémoire de review (« known-patterns ») pour cpm-store

- **Statut** : accepté — 2026-11-14
- **Décideurs** : Quentin (repo perso), conseil LLM (5 advisors + 5 peer-reviews + chairman) + revue utilisateur
- **Cas d'école** : PR #3 `phase1/cpm-core`, commentaires sur `crates/cpm-core/src/model/attribute.rs` (lignes 23, 40, 53)

## Contexte

Les commentaires de review laissés sur les PR meurent dans GitHub : rien ne re-flague un
anti-pattern déjà signalé quand il réapparaît dans un prochain diff. Sur cpm-store (petit repo
perso, ~4 commentaires de review à ce jour), on veut un mécanisme **léger, déterministe et
prouvable**, sans faux positifs qui noieraient le reviewer.

## Décision

1. **Known-patterns déterministes uniquement** : `.vibe/review/known-patterns.toml`
   (un pattern = `id`, `scope` glob, `regex`, `message`, `severity`, `occurrences[]`) +
   `tools/review-check (binaire Rust, AST via syn)`, lancé **sur le diff de la PR** uniquement,
   branché dans le pipeline de review existant. Preuve : sur le diff de la PR #3, les 2
   patterns retenus ressortent en warning (attribute.rs:26, 53, 115) ; sur le diff du
   refactor (PR #5), 0 hit. Un 3e pattern (`manual-serde-impl`) a été testé puis retiré :
   11 faux positifs sur des impls légitimes d'enums — commenté dans le TOML.
2. **Sévérité `warning` pour tout pattern de style/design — jamais de hard gate.** Le reviewer
   est un LLM qui lit tous les warnings (et peut faire des passes dédiées) ; un humain les
   ignorerait. Le **bloquant reste réservé au fonctionnel** : compilateur, tests, `clippy -D`.
3. **Noter dès la 1ère occurrence** (pas de seuil « 2 fois »), et **indexer toutes les
   occurrences** (`file`, `lines`, `since`) — jamais ce qui a remplacé le pattern — pour pouvoir,
   si la règle évolue, lister d'un coup toutes les parties concernées et vérifier que le
   changement est justifiable partout.
4. **Soupape** `// review: ignore <rule-id>` ; **péremption** d'une règle jamais hit depuis N
   reviews (archivée, pas supprimée aveuglément).
5. **Mesurer avant de construire** : grep rétrospectif des patterns sur tout l'historique git
   (`git log -p --all | grep -E <pattern>`). Fait pour la PR #3 : `one_or_many` = 15 ajouts /
   9 fichiers (classe récurrente), `struct Helper` = 2 (one-off).
6. **Pas de sémantique à ce stade** : pas d'embeddings/RAG (corpus trop petit → bruit et faux
   négatifs silencieux). LLM résiduel uniquement si un pattern sémantique est **prouvé manqué
   2 fois** par le grep.

## Conséquences

- Le check est rejouable localement, versionné avec le code, et prouvable (run sur la PR #3,
  les patterns doivent ressortir en warning — critère de falsification).
- Le TOML grossit d'une entrée par nouveau commentaire de review (mode de maintenance, pas de
  « réajustement de poids »).

## Règle associée — AGENTS.md par dossier + TREE.md auto-généré

Pour qu'un agent connaisse le contenu d'un fichier **sans tout lire** :

- `AGENTS.md` à la racine + un par dossier (`crates/cpm-core/`, `src/model/`, `docs/`) :
  identité/contexte du dossier ; le plus proche du cwd s'applique en priorité.
- `docs/TREE.md` : arbre auto-généré par `tools/generate-filemap.py` (source = première ligne
  du `//!` de chaque fichier ; `.vibe/` exclu car déjà découvert par le harness via
  `skill_paths`). **Ne jamais éditer TREE.md à la main** : corriger le `//!` source et relancer
  le script. À synchroniser par pre-commit hook / check CI (même pattern que le FILEMAP de
  dockyard). Équivalent Rust de `__init__.py` pour documenter un dossier : `mod.rs` + `//!`.

## Alternatives rejetées

- **Seuils/poids ajustés itérativement à chaque revue** : boucle manuelle qui pourrit à cette
  échelle ; la récurrence n'est pas un prérequis à la documentation d'un anti-pattern.
- **Embeddings/RAG sémantique (MiniLM-L6-v2 etc.)** : à n≈4 commentaires, c'est du bruit avec
  similarité cosinus ; faux négatifs silencieux (le silence passe pour preuve d'absence).
  Littérature de référence : Bosu et al. (utilité des commentaires de review), OpenCodeReview
  arXiv:2608.09290 (déterminisme partout sauf jugement sémantique), JIT defect prediction.
- **Hard gate sur pattern de style** : freine sans gain, le reviewer LLM lit déjà tous les
  warnings.
