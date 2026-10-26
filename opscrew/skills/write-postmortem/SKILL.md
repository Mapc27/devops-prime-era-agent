---
name: write-postmortem
description: 'Write a blameless postmortem after an incident'
when_to_use: 'after remediation, or when the user asks for a postmortem / summary of the incident'
---
# Postmortem template (blameless)

**Title:** <service>: <symptom> caused by <root cause>
**Impact:** who/what was affected, duration.
**Timeline:** detection (alert/user) → diagnosis → mitigation → recovery verified.
**Root cause:** one paragraph, with evidence ids.
**Resolution:** action taken, approved by whom.
**What went well / what went wrong.**
**Action items:** prevention (tests, alerts, limits), owner = team, not a person.
**Lessons for the agent:** which signal was most diagnostic (to speed up next time).
