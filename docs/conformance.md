# Conformance — checklist SCR (client)

Source : annexe B de [CPM-REST] (`docs/specs.md`). Les SCR client du Message
Storage CPM sont hérités des SCR client de [REST-NMS] ; les items ci-dessous
sont les capacités client requises par [CPM-REST] §5–§7. Chaque item doit finir
couvert par un test (colonne "Test").

Légende : ☐ à faire · ◐ partiel · ☑ fait

## Authentification (spec §5.2.1)

- [ ] Bearer JWT (ID Token OIDC/OAuth2) envoyé sur chaque requête — `CPM-REST §5.2.1.1` — Test :
- [ ] Basic/Digest (credentials préconfigurés) — `§5.2.1.3` — Test :
- [ ] GBA (bootstrapping token) — optionnel — `§5.2.1.2` — Test :

## Dossiers (spec §7.3.2)

- [ ] Lister les dossiers (list folders) — `§7.3.2.3` — Test :
- [ ] Créer un dossier (POST) — `§7.3.2.2` — Test :
- [ ] Lire un dossier (GET) — Test :
- [ ] Renommer un dossier (PUT) — Test :
- [ ] Supprimer un dossier (DELETE) — `§7.3.2.6` — Test :
- [ ] Rechercher des dossiers (POST search, racines) — `§7.3.2.1` — Test :
- [ ] path → id (GET/POST) — Test :
- [ ] Copier objets/dossier vers un dossier cible (POST copyToFolder) — `§7.3.2.5` — Test :
- [ ] Déplacer objets/dossier vers un dossier cible (POST moveToFolder) — `§7.3.2.4` — Test :

## Objets (spec §6.4, §7.3.3)

- [ ] Créer un objet (POST `/objects`, multipart root-fields + attachments) — `§7.3.3.1`, annexe C — Test :
- [ ] Lire les métadonnées d'un objet (GET) — Test :
- [ ] Mettre à jour un objet (PUT) — Test :
- [ ] Supprimer un objet (DELETE) — `§7.3.3.5` — Test :
- [ ] Bulk create — `§7.3.3.2` — Test :
- [ ] Bulk update — `§7.3.3.7` — Test :
- [ ] Bulk delete — `§7.3.3.6` — Test :
- [ ] Recherche d'objets (POST search critères) — `§7.3.3.3` — Test :
- [ ] path/location → objectId (GET/POST) — `§7.3.3.3` — Test :
- [ ] Lire le payload complet d'un objet (GET) — Test :
- [ ] Lire une payload part individuelle (GET `.../payloadParts/{id}`) — Test :
- [ ] Copier un objet vers un dossier cible — `§7.3.3.4` — Test :

## Flags de métadonnées (spec §5.6)

- [ ] Lister les flags d'un objet (GET `.../flags`) — Test :
- [ ] Remplacer la liste complète des flags (PUT) — Test :
- [ ] Tester/ajouter/supprimer un flag individuel (GET/PUT/DELETE `.../flags/{flag}`) — Test :
- [ ] Flags supportés : `\Seen`, `\Answered`, `\Flagged`, `\Deleted`, `\Draft`, `\Recent`, `$Forwarded`, `\read-report-sent`, `Archived` — `§5.6` — Test :

## Subscriptions / notifications (spec §5.5, §7.3.1)

- [ ] Créer une subscription (POST) — `§7.3.1.1` — Test :
- [ ] Créer une subscription + sync initiale (POST) — Test :
- [ ] Lister les subscriptions (GET) — Test :
- [ ] Lire/mettre à jour/supprimer une subscription — Test :
- [ ] Recevoir les notifications (GET, long-poll) avec `lastModSeq` et `restartToken` — `§7.3.1.2` — Test :

## Synchronisation (spec §6.3) — MUST : strict sync uniquement

- [ ] Strict synchronization avec token de dossier par utilisateur — `§6.3.2` — Test :
- [ ] First-time sync : download existant + upload local manquant — `§6.3.3.1` — Test :
- [ ] Steady-state sync : attente de notifications + corrélation cache local — `§6.3.3.2` — Test :
- [ ] Procédure de repli (escape) vers un first-time sync en cas d'erreur irrécupérable — `§6.3.3.2 NOTE` — Test :
- [ ] Ne PAS tenter la simplified synchronization — `§6.3.1` — Test :

## Formats

- [ ] JSON uniquement (Mandatory côté serveur ; XML non supporté) — annexe B — Test :
