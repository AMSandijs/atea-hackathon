# 003 — Offline alert-noise analyst

**One sentence:** point it at a folder of raw Azure Monitor alert exports and get back a
ranked-offenders workbook plus a drafted customer email, without the telemetry leaving
the laptop.

**Status: PARKED.**

---

## The problem

Real and familiar: a 1,580-alert export across 83 rules, where 61% of volume came from
one class of UAT health-check rule and the genuinely broken integration was buried in the
noise. Done by hand today with pandas and a lot of squinting.

## The four questions

**1. Is the AI load-bearing?** Partly. Pandas does the counting. The model groups
near-identical rule names, separates genuine failures from health-check noise, and drafts
the customer comms. Real but modest.

**2. Why must it run locally?** Alert exports are full of customer resource names,
hostnames and IPs — the exact stuff you can't paste into a chat window. Decent, but a
judge could reasonably say "so use a cloud service your customer already approved."

**3. What's the 90-second demo?** Folder in, workbook out. Fine, not thrilling.

**4. Who has this problem?** We do, demonstrably, with a real past example and real
numbers. Strong.

## Known weaknesses

The local angle is good but not unique, and the deliverable is a spreadsheet — hard to
make anyone lean forward. Lowest build risk of anything we considered, which makes it a
decent emergency fallback if a chosen project collapses on Saturday.

## Verdict

**Park.** Worth revisiting as an internal tool independently of the hackathon.
