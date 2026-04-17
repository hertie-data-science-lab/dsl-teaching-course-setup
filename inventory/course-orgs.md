# Course Orgs — Live Inventory

This page is **auto-generated** on a schedule by the `refresh-inventory` workflow. It discovers course orgs by searching GitHub for `.github` repos tagged with the topic `dsl-course-hub` (set automatically by `bootstrap_course.py` when a new course org is bootstrapped).

The discovery source is GitHub itself — no hand-edited list to drift. To add a course, run the **Bootstrap Course Org** workflow; the next cron run picks it up here.

## Active course orgs

<!-- DSL-AUTOGEN-COURSE-ORGS-START -->
<!-- DSL-AUTOGEN-COURSE-ORGS-END -->

## Regenerate on demand

```bash
python3 -m dsl_course.list_orgs --update-file inventory/course-orgs.md
```

Or run **Refresh Course Orgs Inventory** from the Actions tab.

## Related

- Richer context (routing rules, satellite orgs, legacy orgs) lives in the coordination repo's [inventory/course-orgs.md](https://github.com/hertie-data-science-lab/gh-org-strategy/blob/main/inventory/course-orgs.md). That file is hand-maintained; this one is the machine-discovered truth.
