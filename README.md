# DSL Teaching & Course Setup

Central hub for course organization management and faculty workflows at Hertie Data Science Lab.

**Access**: Faculty and admin teams only (enforced via workflow team-check steps)

## Admin Workflows

Setup and management of course organizations.

### `bootstrap-org`

One-time setup for a new course org. Creates:
- Default teams (instructors, students, auditors, course-admin)
- Org settings (2FA enforcement)
- `.github` profile repo with README
- Faculty workflows (`new-semester`, `assign`, `sync-roster`) auto-seeded
- DSL_BOT_TOKEN secret (or validates presence)

**Inputs**:
- `org`: Course org name (e.g. `Hertie-School-Deep-Learning-E1394`)
- `org_name`: Display name (e.g. `Deep Learning`)
- `course_name`: Full course name (optional)
- `set_secret`: Whether to set DSL_BOT_TOKEN (optional)

### `post-migrate`

Retroactive cleanup and migration of historical repos in a course org.

**Phases**:
- `classify`: Analyse repos, identify submissions vs materials (read-only)
- `tag-in-place`: Apply topics, optionally privatise/archive past cohorts
- `migrate`: Move submissions to cohort satellite orgs

**Inputs**:
- `org`: Course org to process
- `phase`: Which phase to run
- `satellite_prefix`: Satellite org prefix for migrate phase (e.g. `hertie-dl`)
- `course_code`: Hertie course code (optional)
- Options for privatising/archiving past cohorts

### `set-classroom-link`

Patch a classroom invite URL into an assignment file in a course website repo.

**Inputs**:
- `course_org`: Course org name
- `website_repo`: Website repo name
- `assignment_file`: Path to assignment file
- `classroom_url`: GitHub Classroom invite URL

---

## Faculty Workflows

Trigger these from your course org's Actions tab. They're automatically seeded when you bootstrap a course org.

### `new-semester` (in course org)

Setup a new semester in your course org:
- Create semester-specific repos (materials, assignments, website)
- Create teams (instructors, students, auditors)
- Deploy website to GitHub Pages
- Optional: set up per-cohort satellite org for submissions

**Inputs**:
- `satellite_org`: Satellite org for submissions (optional)
- `semester`: Semester code (e.g. `f2026`)
- `course_name`, `course_code`: Course identifiers
- `instructors`, `tas`: GitHub logins
- `content_visibility`: private or public

### `assign` (in course org)

Create student assignment repos from a template.

**Options**:
- Per-student repos or per-team repos
- Optional roster file to define team membership
- Dry-run mode to preview

### `sync-roster` (in course org)

Keep teams in sync with a roster file. Runs:
- Automatically: weekly (Mondays 6am UTC)
- On-demand: trigger manually from Actions tab

**Inputs**:
- `semester`: Which semester to sync
- `dry_run`: Preview only

---

## Getting Started

### For admins: Bootstrap a new course org

1. Go to https://github.com/hertie-data-science-lab/dsl-teaching-course-setup → Actions tab
2. Click `bootstrap-org` → Run workflow
3. Fill in: org name, display name, course name
4. Let it run — everything else is automated

### For faculty: Set up a new semester

1. Go to your course org (e.g. `Hertie-School-Deep-Learning-E1394`) → Actions tab
2. Click `new-semester` → Run workflow
3. Fill in: semester, course details, instructor/TA logins
4. Done — repos, teams, and website are created automatically

---

## Integration

- **Implementation**: [gh-org-strategy](https://github.com/hertie-data-science-lab/gh-org-strategy) — Python automation engine
- **Documentation**: [ADRs](https://github.com/hertie-data-science-lab/gh-org-strategy/tree/main/docs/decisions) and [Faculty guides](https://github.com/hertie-data-science-lab/gh-org-strategy/tree/main/docs/for-faculty)
- **Course list**: [inventory/course-orgs.md](https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/inventory/course-orgs.md)
