# Bootstrapped Orgs - Live Inventory

**Auto-generated** by the `refresh-inventory` workflow - do not hand-edit the tables. Discovery is GitHub itself: `bootstrap_course.py` tags each org's `.github` repo (`dsl-course-hub` = course org, `dsl-cohort` = cohort org), and this file lists whatever carries those tags.

## Course orgs

<!-- DSL-AUTOGEN-COURSE-ORGS-START -->

_Auto-generated from GitHub. Discovered via topic `dsl-course-hub` on each org's `.github` repo._

| Org | Course | Code |
| --- | --- | --- |
| [DSL-Demo-Course-E1234](https://github.com/DSL-Demo-Course-E1234) | Machine Learning Fundamentals (Demo) | E1234 |
| [Hertie-DSL-Demo](https://github.com/Hertie-DSL-Demo) | Deep Learning (Demo) | GRAD-DEMO |
| [Hertie-School-Maths-Data-Science-C23](https://github.com/Hertie-School-Maths-Data-Science-C23) | Maths for Data Science | GRAD-C23 |
| [intro-to-data-science-c11](https://github.com/intro-to-data-science-c11) | Introduction to Data Science | C11 |

<!-- DSL-AUTOGEN-COURSE-ORGS-END -->

## Cohort orgs

<!-- DSL-AUTOGEN-COHORT-ORGS-START -->

_Auto-generated from GitHub. Discovered via topic `dsl-cohort` on each org's `.github` repo; the course org is that org's `dsl-course.yml` `course:` pointer._

| Cohort org | Course org |
| --- | --- |
| [DSL-Demo-f2025](https://github.com/DSL-Demo-f2025) | [DSL-Demo-Course-E1234](https://github.com/DSL-Demo-Course-E1234) |
| [DSL-Demo-f2026](https://github.com/DSL-Demo-f2026) | [DSL-Demo-Course-E1234](https://github.com/DSL-Demo-Course-E1234) |
| [DSL-Demo-f2027](https://github.com/DSL-Demo-f2027) | [DSL-Demo-Course-E1234](https://github.com/DSL-Demo-Course-E1234) |
| [Hertie-School-Maths-Data-Science-f2026](https://github.com/Hertie-School-Maths-Data-Science-f2026) | [Hertie-School-Maths-Data-Science-C23](https://github.com/Hertie-School-Maths-Data-Science-C23) |
| [Intro-to-Data-Science-f2025](https://github.com/Intro-to-Data-Science-f2025) | [intro-to-data-science-c11](https://github.com/intro-to-data-science-c11) |
| [Intro-to-Data-Science-f2026](https://github.com/Intro-to-Data-Science-f2026) | [intro-to-data-science-c11](https://github.com/intro-to-data-science-c11) |

<!-- DSL-AUTOGEN-COHORT-ORGS-END -->

## Regenerate on demand

```bash
python3 -m dsl_course.list_orgs --update-file bootstrapped-orgs-inventory.md
```

Or run **Refresh Course Orgs Inventory** from the Actions tab.
