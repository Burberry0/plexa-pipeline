# Plexa Inbox Automation — Status Update

**Date:** October 7, 2026
**Prepared for:** Ryan, Plexa Housing
**Prepared by:** Brandon Kohler

## What the system does

Every rental inquiry that lands in the Plexa inbox is read and sorted automatically within about a minute of arriving. In plain terms, the pipeline does five things:

1. **Filters junk.** Newsletters, vendor pitches, and spam are set aside so only real inquiries move forward. When it is unsure, it keeps the email rather than risk dropping a lead.
2. **Pulls out the details.** From the email text it extracts what the renter is asking for: location, bedrooms, budget, move-in date, pets, number of occupants, and lease length. If a detail is not in the email, it is left blank. The system never guesses.
3. **Sorts the lead into a tier.** Tier 1 means we have location, bedrooms, and at least one more detail, so a match search can start right away. Tier 2 has location and bedrooms only. Tier 3 is missing one of those two and needs a follow-up question.
4. **Drafts a reply.** Each tier gets a tailored reply that confirms what we heard and sets expectations. The reply is written in Plexa's voice and signed from you.
5. **Records everything in Airtable.** Every inquiry becomes a lead record, and every email is logged, so there is one place to see who has written in, what they want, and what we said back.

### A human approves every reply

No reply goes out on its own. When the system drafts one, it posts the original email and the proposed reply to a Slack channel with two buttons: **Approve & send** and **Decline**. Someone on the team clicks one. Approve sends the reply in the same email thread. Decline sends nothing and marks the email as handled. If nobody clicks within 24 hours, nothing is sent.

The same Slack channel also receives a short log entry for every email processed, showing how it was classified and why, so the team can watch the system's judgment in real time.

### A watchdog keeps an eye on the system

A separate monitor checks every 30 minutes that emails are still being processed, that the service is healthy, and that the inbox connection is active. If anything stops, it posts to Slack. A second, independent service watches the monitor itself, so even a total outage gets reported. A daily summary posts each weekday morning with counts by tier and anything that needs a human look.

## Where we stand

**Built and tested**

- The classification service is deployed and live.
- The Airtable base with Leads and Messages tables is created and connected.
- The inbox workflow, the approval step, the Slack logging, and the monitor are all built in n8n.
- A test inquiry was pushed through the full path: it was classified Tier 1, the correct details were extracted, a reply was drafted, and both Airtable records were written.
- The monitor ran on schedule, evaluated all three checks correctly, and posted its first alert to Slack.

**Currently paused**

Everything is switched off at the moment. Nothing is reading the inbox and nothing can send a reply. This is deliberate: the remaining setup steps below touch the live inbox, and we want those done before anything runs unattended.

## What's left before go-live

| Step | Who | Status |
|---|---|---|
| Create two Gmail labels in the Plexa inbox (`Plexa/Needs Attention`, `Plexa/Processed`) and select them in the workflow | Plexa, then Brandon | Pending |
| Confirm the connected Gmail account is the inquiry inbox | Plexa | Pending |
| Decide who sits in the Slack approval channel and is allowed to click Approve | Plexa | Pending |
| Tell us whether inquiries arrive through Zillow or Apartments.com relay addresses | Plexa | Pending |
| Purchase an OpenCode Go subscription | Plexa | Pending |
| Switch the workflows on and run two live tests: one declined, one approved | Brandon | Ready once the above are done |
| Two remaining watchdog checks (outage alert, stale-inbox alert) | Brandon | Ready |
| Build the Airtable dashboard view for the team | Brandon | Ready |
| Supervised period of one to two weeks with every reply approved by hand | Both | After go-live |

The first four items are also in the shared task sheet, where you can mark them done and leave answers.

## What we need from you

1. Complete the four items in the task sheet.
2. Purchase an OpenCode Go subscription. Brandon will send the link and the account details to use.
3. Pick a day for the first live test so someone is in Slack to approve or decline.

## How the system stays safe

- Nothing is sent without a click in Slack.
- A hard kill switch on the service turns off reply drafting entirely, while classification and record-keeping continue.
- Turning off the inbox workflow stops all processing within a minute.
- Every email and every decision is logged in Airtable, so anything can be reviewed after the fact.
