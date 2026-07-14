# DSL Teaching & Course Setup

Central registry of the workflows that deliver courses at the Hertie Data Science Lab.
Everything faculty-facing is a **GitHub Actions button**; the Python in `dsl_course/` is the
single implementation behind every button.

## The model

Two org tiers:
1. the **course** org is the faculty-facing control plane - the historical registry of
   course materials, persistent across years, where faculty push version-controlled materials
   from;
2. the **cohort** org is the per-year student-facing delivery target - materials are released
   here, student assignments are submitted and assessed here, and student-facing features
   (onboarding, the website) live here.

```mermaid
flowchart TB
  subgraph COURSE["COURSE org — e.g. Hertie-School-Deep-Learning-E1394 (persistent)"]
    mat["course-materials-f2026 · PRIVATE<br/>lectures/00_.../ + readings/00_.../ (+ syllabus, README)"]
    tmpl["assignment-1-f2026 ... · PRIVATE<br/>template repos (is_template) + autograder"]
    gh[".github · PUBLIC<br/>profile (auto) + ALL faculty buttons + cohort registry"]
  end

  subgraph COHORT["COHORT org — e.g. Deep-Learning-f2026 (per-year)"]
    welcome["welcome · PUBLIC<br/>Join issue → onboard.yml (enrol)"]
    cfg["classroom-config · PRIVATE<br/>students.csv roster + grades"]
    cmat["materials · PRIVATE<br/>released lectures/readings (students-team read)"]
    repos["&lt;assignment&gt;-&lt;handle&gt; · PRIVATE<br/>one private repo per student (generated; autograder rides along)"]
    team["students team · PRIVATE"]
  end

  pub["&lt;course-org&gt;.github.io · PUBLIC (opt-in)<br/>open-courseware site — hosts shared lectures + readings"]

  COURSE -->|"release / generate (bot token, cross-org)"| COHORT
  gh -.->|"Publish course website (opt-in)"| pub

  classDef public fill:#e6f4ea,stroke:#2e7d32,color:#1b5e20;
  classDef private fill:#f3f3f3,stroke:#8a8a8a,color:#3c3c3c;
  class gh,welcome,pub public;
  class mat,tmpl,cfg,cmat,repos,team private;
```

Each cohort gets an auto-deployed `<cohort>.github.io` site whose material links are private
(enrolled students only). Optionally, a course can also publish a **public**
`<course-org>.github.io` open-courseware site that shares its lectures + readings with the
world (see [Optional: public course website](#optional-public-course-website)).

## Deploying a course

Three phases - **set up the course** (once), **add a cohort** (per year), then **run it**
(release weekly).

- **▶ Workflow runbooks — [`docs/faculty-and-instructors/`](docs/faculty-and-instructors/README.md) — start here.** The step-by-step guide, one per workflow, each naming the exact button, inputs, and order.
- **Worked example:** [`example-course/`](example-course/README.md) - a dummy course you can stand up end to end alongside the runbooks.
- **Input schema** (reference): [`docs/faculty-and-instructors/required-input-schema.md`](docs/faculty-and-instructors/required-input-schema.md) - the what-goes-where data contract.
- **Deployment checklist** (reference): [tickable, deploy-ordered](docs/faculty-and-instructors/required-input-schema.md#deployment-checklist) - to track progress once you know the flow.

The only manual steps are creating each org in the GitHub web UI
([github.com/account/organizations/new](https://github.com/account/organizations/new) - there
is no org-creation API) and inviting **`hertie-dsl-bot`** as **Owner** (Org → People →
Invite; the DSL team must **accept** the pending invite before you bootstrap -
[which account?](docs/admin/admin-setup.md#the-bot-account)); everything after that is a button.

## Faculty actions

Every faculty action is a GitHub Actions button in the course org's bootstrapped `.github`
Actions tab. See the **[workflow runbooks](docs/faculty-and-instructors/README.md)** for the flows, or the
**[actions reference](docs/faculty-and-instructors/actions-reference.md)** for a one-page summary of every button.

---

**Admin & developer reference** (faculty delivering a course don't need this):
[`docs/admin/`](docs/admin/) - the [architecture](docs/admin/architecture.md) (system design,
token propagation, who-can-run access, the code map) and [operational setup](docs/admin/admin-setup.md)
(the bot credential, exact PAT scopes, the token/secret model).
