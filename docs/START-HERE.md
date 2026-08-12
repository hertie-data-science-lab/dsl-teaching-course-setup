# Start here

This system provisions and runs GitHub course orgs for the Hertie Data Science Lab: a course is built once in a **course org** and delivered each year into a **cohort org**.

## Where do I go?

| If you are... | Go to |
|---------------|-------|
| **Setting up a brand-new course** | [faculty & instructors runbooks](faculty-and-instructors/README.md) - runbooks [01](faculty-and-instructors/01-new-course-org.md)-[03](faculty-and-instructors/03-add-assignment-to-course.md) |
| **Starting a new cohort / semester of an existing course** | [04 New cohort org](faculty-and-instructors/04-new-cohort-org.md) onwards |
| **Joining as a TA or faculty assistant (FA)** | [`ta-fa/`](ta-fa/README.md) |
| **A course admin inheriting a running course** | [`admin/course-admin.md`](admin/course-admin.md) |

Reference, not reading: [actions reference](faculty-and-instructors/actions-reference.md) (every
button, one line each), [input schema](faculty-and-instructors/required-input-schema.md) (every
file and column), [architecture](admin/architecture.md) (how it works).

## Glossary

**Course org** - the persistent org for a course (e.g. `DSL-Demo-Course-E1234`). Holds the
materials repos, the assignment templates, and the control panel. Lives across all years.

**Cohort org** - one org per delivery (e.g. `DSL-Demo-f2026`). Holds the roster, released
materials, per-student assignment repos, grades and the cohort website. Discarded-in-place at the
end of the year; next year gets a fresh one.

**Tag** - the `fYYYY` / `sYYYY` suffix naming a delivery (`f2026` = Fall 2026, `s2027` = Spring
2027). It scopes the year's content repos (`course-materials-f2026`, `assignment-1-f2026`) and the
teams that can push to them.

**Control panel** - the course org's `.github` repo. Its **Actions** tab is where *every*
workflow button lives, for both the course org and all of its cohorts. Cohort orgs
have no buttons of their own; their front page is student-facing.


**`course-admin` team** - the course org's standing owners of the course, declared once in the
course org's `.github/dsl-course.yml` (`course_admins`) and mirrored down into every cohort org.
Unlike instructors, it is not per-cohort.

**Single source of truth (SSOT)** - the one file or repo that a fact is edited in; everything else
is generated from it. The course org is the SSOT for content; each cohort's `classroom-config` is
the SSOT for that cohort's roster, teams, schedule and grades.

**The bot (`hertie-dsl-bot`)** - the machine account that performs every cross-org action. It must
be an **Owner** of every course and cohort org - the one irreducible manual step. No human ever
holds its token. See [admin-setup](admin/admin-setup.md#the-bot-account).
