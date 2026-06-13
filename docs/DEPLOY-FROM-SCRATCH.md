# Deploy a course from scratch - the full set of inputs

This is the authoritative checklist of **every input** needed to stand up a fully working
course + cohort from nothing, and the order to supply them. It is engine-canonical (it
describes the buttons in this repo, not any one demo). For a ready-to-run worked example
with dummy data, see [`example-course/`](../example-course/README.md).

Everything faculty-facing is a **GitHub Actions button** - no CLI ([ADR 0008]). The Python
in `dsl_course/` is the single implementation behind every button.

## What you end up with

```
COURSE org   (persistent, private)              COHORT org   (per year, private)
  .github/dsl-course.yml  identity+people+schedule  welcome      Join issue -> onboard
  materials-f2026   lectures/ + readings/    ──►   classroom-config  students.csv (PRIVATE)
  assignment-N-f2026  template repos          ──►  materials         released weeks
  .github  console + buttons                  ──►  <assignment>-<handle>  per-student repos
                                                   <cohort>.github.io   auto-generated site
```

The course org is the source of truth; the cohort org receives releases of it.

## The input-schema contract

Every part of a course has **one canonical place**. Put your inputs there, run the
buttons, and the pipeline reads them and generates a full, delivery-ready course +
website. Nothing about the course is hand-built on the site - it is all *derived* from
these inputs, so re-running is idempotent and a new cohort is a re-run.

| Input | Canonical place | Read by | Becomes on the site / cohort |
|-------|-----------------|---------|------------------------------|
| **Course identity** (name, code) | `.github/dsl-course.yml` → `org_name`, `course_name`, `course_code` | `site` | site title + header |
| **Semester** | derived from the cohort org's `fYYYY`/`sYYYY` tag | `site` | "Fall 2026" + schedule anchor |
| **People** (instructors, TAs) | `.github/dsl-course.yml` → `people:` block (`name`, `photo`, `url`, `title`) | `site` | instructor/TA cards (institutional headshots + bio links) |
| **Schedule** (semester start, due dates, exams) | `.github/dsl-course.yml` → `schedule:` block | `site` | the schedule table (lectures, due dates, exams) |
| **Lectures** | `materials-fYYYY/lectures/week-N/` (any files) | `release` → `site` | weekly lecture entries linking the released files |
| **Readings** | `materials-fYYYY/readings/week-N/` (any files) | `release` → `site` | weekly reading links |
| **Syllabus** | `materials-fYYYY/` root file matching `*syllabus*` | `release --syllabus` | cohort root + syllabus link |
| **Assignments** | `assignment-N-fYYYY` template repo: `README.md` (brief), `starter.*`, `tests/`, `autograder/grade.py`, `.github/workflows/autograde.yml`, `solution` branch | `release-assignment` → `site` | assignment briefs on the site + one private `<slug>-<handle>` repo per student; each push runs the autograder |
| **Roster** | cohort `classroom-config/students.csv` (`student_id, hertie_email, name, section`) | `sync_roster`, `assign`, onboard | enrolment + per-student provisioning |

So `.github/dsl-course.yml` is the **course config contract** (identity + people + schedule);
the `materials-fYYYY` repo is the **content contract** (lectures/readings/syllabus by week);
the `assignment-*-fYYYY` template repos are the **assignment contract**; and the cohort
`students.csv` is the **roster contract**. The pipeline -
`Bootstrap → Release materials/assignment → (auto) Sync site` - turns those inputs into the
running course. Anything you don't supply is synthesised or skipped, never blocks.

## The inputs, grouped

### A. One-time, manual (cannot be automated)

| # | Input | How / where | Notes |
|---|-------|-------------|-------|
| A1 | **Create the course org** | GitHub web UI | GitHub has **no org-creation API** ([ADR 0011 §9]). Add the bot account as an **owner**. |
| A2 | **Create the cohort org** | GitHub web UI | Same - one per year. Add the bot as owner. |
| A3 | **`DSL_BOT_TOKEN`** | A classic PAT (demo) or GitHub App (prod) | Scopes: `repo` + `admin:org` + `workflow`. Must be **owner on both orgs**. This is the only secret. See [Token](#token). |

Everything below is a button or a file edit.

### B. Course org content (persistent - set once, reused every cohort)

| # | Input | Supplied via | Mandatory | Stored as |
|---|-------|--------------|-----------|-----------|
| B1 | Course identity: `org`, `org_name`, `course_name`, `course_code` | **Bootstrap Course Org** button inputs | org + org_name | `.github/dsl-course.yml` |
| B2 | **People** (instructors + TAs: name, photo, bio link, title) | Edit the `people:` block in `.github/dsl-course.yml` | for the site cards | declared input → cards carry institutional headshots + bio links. *(If omitted, falls back to the `instructors`/`teaching-assistants` GitHub teams → GitHub avatars.)* |
| B4 | **Materials**: a `materials-fYYYY` repo with `lectures/week-N/` and `readings/week-N/` folders | **New materials repo** button scaffolds it; you add files | yes | course org repo |
| B5 | Syllabus / root README (optional) | Files at the materials-repo root | optional | copied to the cohort on release if toggled on |
| B6 | **Assignments**: one `assignment-N-fYYYY` **template** repo each (starter + autograder on `main`, empty `solution` branch) | **New assignment** button scaffolds it; you add the brief + starter | yes | course org template repos (`is_template`) |
| B7 | **Schedule dates** (assignment due dates, exam dates, real semester start) | Edit the `schedule:` block in `.github/dsl-course.yml` | optional (synthesised if blank) | see [Schedule](#the-schedule) |

### C. Per-cohort (each year)

| # | Input | Supplied via | Mandatory |
|---|-------|--------------|-----------|
| C1 | The empty cohort org name | **Bootstrap cohort** button | yes |
| C2 | **Roster**: registrar columns of `students.csv` (`student_id, hertie_email, name, section`) | Edit `classroom-config/students.csv` (private) | yes |

`github_handle` and `github_id` are **left blank** - students fill them by onboarding (below).

### D. Per-student (self-service, no faculty input)

A student opens a **Join** issue in `welcome` and types their **student ID**. The onboard
workflow does the rest. See [How students are managed](#how-students-are-managed).

## Step-by-step

**Course (once):**
1. Create the course org in the web UI; add the bot as owner. *(A1)*
2. This repo's Actions tab → **Bootstrap Course Org** (`org`, `org_name`, `course_name`,
   `course_code`). Sets teams, 2FA, the `.github` profile + **all the buttons**, and
   propagates `DSL_BOT_TOKEN`. *(A3, B1)*
3. Edit the **`people:`** block in `.github/dsl-course.yml` (instructors + TAs). *(B2)*
4. **New materials repo** → fill `lectures/week-N/` + `readings/week-N/` with your files.
   *(B4, B5)*
5. **New assignment** (once per assignment) → fill the brief (`README.md`) + starter. *(B6)*
6. (Optional) edit the **`schedule:`** block in `.github/dsl-course.yml`. *(B7)*
7. **Refresh actions** so every content repo gets its run-from-repo buttons, the repo
   secret is propagated, and all dropdowns populate from live state.

**Cohort (per year):**
8. Create the cohort org in the web UI; add the bot as owner. *(A2)*
9. Course org → **Bootstrap cohort** (the cohort org name). Seeds `welcome` + roster,
   tightens permissions, scaffolds the website, registers the cohort. *(C1)*
10. Replace the starter row in `classroom-config/students.csv` with registrar data. *(C2)*

**Run the course:**
11. **Release materials** (pick cohort + week) → that week's lectures/readings appear in the
    cohort `materials` repo and on the site. Repeat weekly ("each week opens up").
12. **Release assignment** (pick cohort + assignment) → freezes a cohort template, then
    generates one private `<assignment>-<handle>` repo per onboarded student.
13. Students onboard themselves via the Join issue; **Enroll student** is the faculty override.

## How students are managed

Student lifecycle is **two separate stages** - *enrol once, provision per assignment*:

1. **Enrolment (access).** The registrar seeds `students.csv` with `student_id` (+ email,
   name, section); `github_handle`/`github_id` start blank. A student opens a **Join** issue
   in the public `welcome` repo and types **only their student ID** (never PII - that's
   already on the private roster). `onboard.yml` (the one cohort-side action):
   - takes the issue **author** as the authenticated, unspoofable GitHub handle;
   - matches the typed `student_id` against the private roster - **non-enrolees are
     rejected** with a clear comment;
   - writes the handle + immutable `github_id` back onto that row (keyed on the id, so a
     later handle rename never orphans repos), serialised against append races;
   - grants **org membership + `students` team** (the team carries cohort-private read, so
     released materials unlock);
   - comments confirmation, labels `enrolled`, closes the issue.

   The faculty override is the **Enroll student** button (type a handle; a blank handle
   reconciles the whole roster). `sync_roster` materialises team membership from the CSV.

2. **Provisioning (per-assignment repos).** **Release assignment** reads the roster and, for
   each **onboarded** row (non-blank handle), native-`generate`s a private
   `<assignment>-<handle>` repo from the frozen cohort template and adds the student as
   collaborator. Not-yet-onboarded rows are skipped; re-running is idempotent.

**Submission** is a plain `git push` to `main` in the student's repo - no CLI, no accept step.

**Removal / rollover:** drop the row from `students.csv` and re-run **Enroll student** with a
blank handle and `--prune` to reconcile team membership. (Repo archival/erasure on cohort
rollover is a documented manual runbook - see GDPR items in [ADR 0010].)

Roster columns:

| Column | Filled by | Mandatory |
|--------|-----------|-----------|
| `student_id` | registrar (seed) | ✅ match key |
| `hertie_email` | registrar (seed) | ✅ grade-export key; PII → private only |
| `name` | registrar (seed) | ✅ |
| `github_handle` | **onboarding** | blank until the student joins |
| `github_id` | **onboarding** | blank until the student joins |
| `section` | registrar (seed) | ✅ |

## People

Instructor/TA cards are a **declared input**: the `people:` block in the course
`.github/dsl-course.yml`. This lets cards carry institutional headshots + bio links
rather than GitHub avatars. The first instructor is the "featured" one. Edit it and run
**Sync site**:

```yaml
people:
  instructors:
    - name: "Prof. Jane Doe"
      title: "Professor of ..."        # optional
      photo: "https://.../jane.jpg"    # image URL (shown on the card)
      url: "https://.../profile/jane"  # bio / profile link
  teaching_assistants:
    - name: "A. N. Other"
      photo: "https://.../other.jpg"
      url: "https://.../profile/other"
```

If there is no `people:` block, the site falls back to the GitHub `instructors` /
`teaching-assistants` teams (GitHub display name + avatar + profile link).

## The schedule

The cohort website schedule is generated, not hand-built. By default dates are
**synthesised**: semester start = 1 Sep (fall) / 1 Feb (spring) of the cohort's `fYYYY`
tag; lectures weekly from there; assignments every 14 days; exams at weeks 8 and 15.

To set **real** dates, edit the optional `schedule:` block in the course
`.github/dsl-course.yml` and run **Sync site**:

```yaml
schedule:
  semester_start: 2026-09-07          # YYYY-MM-DD
  assignments:                        # keyed by assignment slug (the repo name minus -fYYYY)
    assignment-1: 2026-10-13
    assignment-2: 2026-11-17
  exams:
    - name: MidTerm Exam
      date: 2026-11-03
    - name: Final Exam
      date: 2026-12-15
```

Anything you leave out keeps its synthesised value, so the block is fully optional and
backward-compatible.

## Token

One secret, `DSL_BOT_TOKEN`, runs every workflow. It needs, **on both orgs**: repo admin
(create/generate repos, topics, settings), org members (invite + team), and contents R/W.

- **Demo:** a classic PAT with `repo` + `admin:org` + `workflow`.
- **Free-plan caveat:** org secrets don't reach private repos, so Bootstrap sets it as an
  *org* secret (public `.github`/`welcome`) **and** Refresh propagates it as a *repo* secret
  on each private content repo.
- **Production target:** a GitHub App (fine-grained, short-lived), or GitHub Team/Enterprise
  (where org secrets reach private repos and the propagation is unnecessary).

## Known limits (not blockers)

- **Autograding** runs a minimal pytest autograder on every push to `main` (the submission):
  it runs the assignment's `tests/`, writes `result.json` (`{score, max, tests}` - the
  C50-style contract for later score collection) and a score summary on the Actions run.
  Swap pytest for Otter/nbgrader without changing the workflow. Score-collection into
  `scores.csv`/Moodle is the remaining piece ([ADR 0010 §2/§4]).
- **Moodle** roster-in / grade-out is manual CSV until Hertie IT enables Web Services.
- **Pages are public** on the Free plan; access-controlled once on Campus/Enterprise.
- GDPR (retention, erasure, DPA, DPO sign-off) must be settled before any live cohort.

[ADR 0008]: https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/docs/decisions/0008-no-cli-for-faculty.md
[ADR 0010]: https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/docs/decisions/0010-classroom50-inverted-org-model.md
[ADR 0011 §9]: https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/docs/decisions/0011-realized-faculty-console-workflow.md
[ADR 0011]: https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/docs/decisions/0011-realized-faculty-console-workflow.md
