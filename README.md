# PageMetrics

A responsive, dependency-free browser implementation of Team T055's library analytics specification.

## Run

Requires Python 3 and Node.js 18+ (tests only).

```sh
npm start
# http://localhost:5173
npm test
```

## Implemented

- Combined inclusive date, subject, Dewey class, resource, format and user-segment filters.
- Daily, Monday-based weekly, monthly and seasonal activity; seasonal convention: Jan–Mar winter, Apr–Jun spring, Jul–Sep summer, Oct–Dec autumn.
- Total checkouts, unique anonymous readers and on-time rate. Only RETURNED_ON_TIME and RETURNED_LATE count toward the rate denominator; no returned loans yields N/A.
- Format mix, subject and reader-segment charts, most/least borrowed title ranking and aggregate CSV export.
- CSV imports with strict header allowlist, anonymous token convention, required fields, date/status/segment/format validation and duplicate detection within the import. Error reports never display cell values.
- Successful imports replace browser-local data; partial imports save accepted records; invalid files and storage failures retain the previous dataset.
- Responsive layout, accessible labelled controls, empty states, sample data and CSV template.

## Deliberate limitations

This is a browser-local implementation, not the full client-server architecture in the assignment. No institutional authentication, server-enforced role access, shared database, or audit service is implemented. Do not use it to enforce faculty subject permissions or handle confidential institutional records. Browser localStorage is unencrypted and scoped to the browser/origin. Owner-private site hosting does not provide the assignment's application-level roles.

Privacy checks reject extra columns and require anonymous IDs, but cannot detect all personal information embedded in titles or other free text. Data must be anonymized upstream. File limit is 5 MB. Rankings only include resources with matching loans, since there is no separate complete catalogue. Sample data is fictional and fixed to 2026. The resource table displays the first matching loan's format for each resource.

Next production work: authenticated backend endpoints, librarian-only import authorization, subject-scoped queries for faculty, transactional database replacement, session expiry and persistence tests.
