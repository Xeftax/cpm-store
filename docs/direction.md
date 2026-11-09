# Issue and Project Conventions

This page describes how we organise development tracking in this repo: where things live, how to file new work, and how to read the project board.

> Day-to-day product/agile tracking remains in **Jira**. This system is for **developer-level direction**: bugs, refactors, spikes, sub-tickets, technical follow-ups that don't deserve a Jira epic.

## Where things live

- **Project board:** none declared (`[board] project_number` in `dockyard.toml`)
- **Issues:** this repository's Issues tab
- **Templates:** `.github/ISSUE_TEMPLATE/` (Epic, Spike, Bug, Feature, Task)

## Issue Types (org-level)

Every issue carries one of the three Tetrixx-SG Issue Types:

| Type        | When to use                                                                      |
| ----------- | -------------------------------------------------------------------------------- |
| **Task**    | Default for technical work — adapters, refactors, infra, spikes, cleanup, audits |
| **Feature** | New user-facing or dev-facing capability                                         |
| **Bug**     | Something doesn't work as it should                                              |

There is **no `Epic` Issue Type**. Epics are just Task or Feature with sub-issues attached — you recognise them by the **Sub-issues progress** field on the board, set via the native Sub-issues link.

`To investigate` is the preliminary status for spikes (`Kind=spike`) — they live there until their ADR / design note is delivered, then go straight to `Done`. Other issues skip it and start at `Todo`.

## Project board — fields drive organisation

Everything that distinguishes issues lives on the board as a **single-select field**, not as labels. This is what lets us slice the board "By Area", "By Client", "By Kind", "By Cloud" etc.

| Field    | Question                     | Values                                                                         | When to leave empty                        |
| -------- | ---------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------ |
| `Status` | Where in the workflow ?      | To investigate / Todo / In Progress / Plan Review / Code Review / Done? / Done | never                                      |
| `Prio`   | What priority ?              | now / next / later                                                             | when not yet triaged                       |
| `Area`   | Where in the system ?        | see `### Area — where in the system` below                                     | never                                      |
| `Kind`   | What nature of deliverable ? | adapter / provider / spike / doc / cleanup                                     | when it's a regular code feature / bug fix |
| `Client` | For which client ?           | this repo's own client set                                                     | when cross-client or not client-specific   |
| `Cloud`  | Which cloud target ?         | aws / gcp / both                                                               | when not cloud-specific                    |

Not every field applies to every repo's board — use the ones this repo has configured.

### Status — the work lifecycle

`Status` is **two-gated**: a ticket is reviewed twice — first its **plan**, then its **code**. Reviewing a plan is far cheaper than reviewing code that went the wrong way, and it is where we resolve disagreements about technical strategy before anyone writes code.

| Status           | Meaning                                                                                                                                                                                                               |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `To investigate` | Upstream research: an idea exists but the need/approach is undefined. Explore (often `Kind=spike`) before it becomes an actionable ticket — the deliverable is usually one or more well-scoped tickets.               |
| `Todo`           | Defined and ready to be picked up; scope is clear enough to start.                                                                                                                                                    |
| `In Progress`    | Active work — **either** drafting the implementation plan, **or** coding once the plan is acknowledged.                                                                                                               |
| `Plan Review`    | **Gate 1.** A plan is written in the issue body and awaits the team's validation of the *direction* (not the code). Reviewers ack with 👍 or raise questions in comments. Returns to `In Progress` once acknowledged. |
| `Code Review`    | **Gate 2.** A PR is open and ready for code review. Link the PR on the issue.                                                                                                                                         |
| `Done?`          | **Confirmation buffer.** Claude or the sync routine believes the work is resolved (e.g. a merged PR closed it implicitly) but won't close it: a human confirms and moves it to `Done`, or moves it back if not.       |
| `Done`           | Merged / delivered. **Setting `Done` auto-closes the issue** on this board.                                                                                                                                           |

The normal path: `Todo → In Progress → Plan Review → In Progress → Code Review → Done`.

**Triviality escape hatch:** small or obvious work (a one-line fix, a mechanical change) skips Gate 1 — go straight `In Progress → Code Review`. Don't impose the plan gate where there's nothing to disagree about. Gate 1 is for work where the strategy is non-obvious or contested.

**`Done?` is for automation, not humans.** Because `Done` is irreversible (it closes the issue), Claude and the drift-detection routine never set `Done` directly — they set `Done?` and leave the final call to a human. It can be entered from any state (a routine that spots a merged-but-unclosed issue jumps straight there). A human working interactively can move to `Done` themselves.

### Area — where in the system

This repo declares no areas yet. Name them under `[direction.area]` in `dockyard.toml`, one `value = "what it comprises"` each, and `dockyard sync` renders them here.

### Kind — nature of the deliverable

Use when the work fits one of these clear clusters. Otherwise, leave empty.

| Value      | When to use                                                         |
| ---------- | ------------------------------------------------------------------- |
| `adapter`  | Implementation of a Port (Storage, Messaging, Secrets, Analyzer, …) |
| `provider` | Client/provider-specific package or schema                          |
| `spike`    | Time-boxed investigation; deliverable is an ADR or design note      |
| `doc`      | Pure documentation work (runbook, planning) — no investigation      |
| `cleanup`  | Refactor of obsolete code or housekeeping of stale branches         |

Note: there is no `kind:infra`. Infrastructure work is identified by `Area=infra` instead.

## Labels — minimal, for cross-cutting flags only

| Label                   | Use                                                                                       |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| `touches:<repo>`        | Requires coordinated changes in another repo (e.g. `touches:tfin-api`, `touches:tfin-ui`) |
| `status:blocked`        | Blocked on external dependency or decision                                                |
| `status:waiting-review` | _Superseded by `Status=Code Review` — don't use going forward._                           |
| (default GH labels)     | Used by automation (dependabot, etc.) — don't bother filing manually                      |

### Don't recreate as labels

- ❌ `area:*`, `cloud:*`, `client:*`, `kind:*` — all live as board fields
- ❌ `epic`, `spike` — Issue Type + `Kind=spike` covers this

## Title conventions

- **No type prefix** in titles (`Epic:`, `Bug:`, `Spike:`, `Adapter:` are redundant with Issue Type and board fields)
- Descriptive titles that describe the outcome — e.g. `GCSStorageAdapter implementing StoragePort`, not `Adapter: GCSStorageAdapter`
- Specific over generic — describe the concrete change, not the general area

## Issue body structure

Templates enforce the shape. Common sections:

- **Goal** — one paragraph stating the outcome
- **Why now** — bullet points; strategic reason, blockers being unblocked
- **Scope (In / Out)** — explicit inclusion and exclusion lists
- **Acceptance criteria** — checklist
- **References** — links to design docs, planning notes, related PRs

For spikes: replace **Goal** with **Question**, replace **Scope** with **Deliverable + Out of scope**, add **Time box**.

## Implementation plans (the Plan Review gate)

When a ticket reaches Gate 1, the implementer writes the plan **in the issue body** (not in a comment). The body is the evergreen, current truth; as the discussion changes the plan, **edit the body** so it always reflects the agreed direction. Comments and 👍 reactions carry the discussion and the acknowledgement — not the plan itself.

A plan exists to be **acknowledged quickly**. The bar: a reviewer can read it and either react 👍 or raise exactly one question — without wading through noise. Optimise for that.

**Format** — follow this reading order:

````markdown
## Context
2–3 lines: where this sits in the system, what triggers it now.

## Need
The problem to solve, stated as a *desired outcome* — not a solution.
The most important section: if a reviewer reads only this, they know what "success" means.

## Strategy
- ✅ **Do** — the chosen approach, in key points.
- ❌ **Don't** — the roads deliberately not taken, and why. (Often the most useful part to review.)


## Impact
The file/folder tree the implementation will touch:
​```
path/to/module/...
​```



## Annex (optional — only when it helps the reviewer decide)
- UI change → an HTML mockup or an ASCII layout
- Flow / pipeline → a node graph in ASCII or a diagram
- New model / entity → the Pydantic / schema sketch
````

**Hygiene rules:**

- **One concern per ticket.** If a ticket holds two separable ideas, split them into sub-issues. If they're close and simple, keep them in one body but segregate them under clear headings — never interleave.
- **Concise, no mixed ideas.** Prefer explicit links over implicit context. If something is unclear, ask in a comment rather than padding the plan.
- **The plan replaces nothing at filing time** — `Goal` / `Acceptance criteria` from the template still frame the ticket. The plan deepens `Need` and adds `Strategy` / `Impact` / `Annex` when the work is picked up.

## Sub-issues

Use GitHub's native Sub-issues mechanism (right rail of an issue → "Sub-issues" → "+ Add"). The board's `Sub-issues progress` and the "By Parent issue" grouping depend on this. Don't rely on `Parent: #X` text in the body — that's a fallback for readability, not the mechanism.

## Milestones

Milestones are used for **time-bound large initiatives** that span multiple epics or have a target completion date, e.g.:

- `<Milestone name>` — <what it covers> (epic #NNN + sub-issues)

Not every epic needs a milestone — only when there's a clear time horizon to track against.

## Filing new work

1. Pick the right template (`.github/ISSUE_TEMPLATE/`) — the Issue Type is set automatically
2. Add `touches:*` / `status:*` labels if relevant (the only labels you should think about)
3. Once the issue is created, add it to this repo's project board (see `## Where things live` above) — the native `Auto-add to project` workflow does this (widen its filter beyond `label:bug` so all issues are added); adding it is what lets `Item added → Todo` fire
4. Set `Area`, `Prio` on the board (always)
5. Set `Kind`, `Client`, `Cloud` if applicable
6. If it's a sub-issue: open the parent epic, add this issue under "Sub-issues"

## Project board views

| View      | Layout         | Useful for                                         |
| --------- | -------------- | -------------------------------------------------- |
| Roadmap   | Board (Status) | Standup / weekly view                              |
| By Area   | Board (Area)   | "What's happening in this area this week?"         |
| By Cloud  | Board (Cloud)  | AWS vs GCP work split                              |
| By Client | Board (Client) | Multi-client tracking                              |
| By Kind   | Board (Kind)   | "Which spikes are open?", "Adapters left to build" |
| Backlog   | Table          | Bulk triage and re-prioritisation                  |

## Native board workflows

The board's `Status` lifecycle is driven end-to-end by GitHub's **built-in Project workflows** (Settings → Workflows), so any custom sync routine only handles what the built-ins can't (custom field logic). All of the following are meant to be **on** — they collectively cover the full lifecycle:

| Workflow                       | Trigger → effect                                    |
| ------------------------------ | --------------------------------------------------- |
| Auto-add to project            | new/updated repo item matches → add it              |
| Item added to project          | issue/PR added → `Status = Todo`                    |
| Pull request linked to issue   | PR linked → `Status = In Progress`                  |
| Code changes requested         | PR review requests changes → `Status = Code Review` |
| Code review approved           | PR approved → `Status = Code Review`                |
| Pull request merged            | PR merged → `Status = Done`                         |
| Item closed                    | issue/PR closed → `Status = Done`                   |
| Item reopened                  | issue/PR reopened → `Status = Code Review`          |
| Auto-close issue               | `Status = Done` → close the issue                   |
| Auto-archive items             | closed issue idle >2w → archive                     |
| Auto-add sub-issues to project | sub-issues inherit board membership                 |

Auto-close only fires on a **real** close, which needs `Closes #N` in the PR body (a bare `(#N)` mention does not — see the PR template).

One config caveat when enabling: `Auto-add to project`'s filter may default to something narrow (e.g. `is:issue,pr is:open label:bug`) — widen it (drop the label filter) if the intent is to auto-add all repo issues/PRs.

<!-- Everything above is the estate's convention and is overwritten on sync, except the
     board and issues links, the Area table and the Client values, which sync renders from
     the repo's own `[direction]` (and `[board]`) in `dockyard.toml`. A repo
     needing sections of its own opens a `dockyard:keep` region under whatever name it
     chooses, anchored beside a line above that this file carries exactly once — it adds;
     it never overrides what is here. A repo needing a different convention entirely
     declines this file in `dockyard.toml`'s `decline` list instead. -->
