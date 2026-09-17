## Arc One Bridge

The integration contract between Arc-One and this ERPNext/HRM site.

Arc-One previously talked to Frappe two ways, with nothing on this side owning the
contract: direct REST calls outbound, and ~84 stock Frappe `Webhook` documents
inbound. Webhooks are fire-and-forget — no retry, no ordering, no record that a
delivery happened — so anything dispatched while Arc-One was restarting was lost
permanently.

This app replaces the inbound half with a **change feed that Arc-One pulls**.

### Why pull

A push design cannot survive the *receiver* being down. A cursor the consumer owns
makes recovery the ordinary path rather than a special case: if Arc-One was offline
for an hour, its next poll catches up. If this site was offline, the same. Nothing
needs a retry queue, a dead-letter queue, or delivery bookkeeping — the cursor *is*
the state.

It also removes the token that expired every 24 hours inside every Webhook document
and silently stopped all replication.

### How it works

`doc_events` fires a wildcard hook on every document write. If the DocType is listed
in **Arc One Sync Settings**, a row is appended to **Arc One Change Log**:

    name (autoincrement)   the cursor — monotonic, gap-free, self-ordering
    ref_doctype
    ref_name
    event                  insert | update | submit | cancel | trash

**No payload is stored.** The consumer reads a page, collapses it to distinct
`(ref_doctype, ref_name)` and fetches the *current* state of each document. That
makes applying the feed idempotent — replaying any range converges on the same
result — and a document edited fifty times is fetched once.

Deletions are the exception: once a document is gone there is nothing left to fetch,
which is the main reason a plain `/api/resource` poll cannot replace this feed.

### Layout

    arc_one_bridge/
      hooks.py                     doc_events + scheduler wiring
      api/
        change_feed.py             changes(), cursor_head()
        reconciliation.py          reconcile()
      events/
        change_recorder.py         the doc_events handlers - thin, never raise
      utils/
        permissions.py             require_sync_role(), shared by every endpoint
      arc_one_bridge/              module
        doctype/
          arc_one_change_log/      owns record() and prune()
          arc_one_sync_settings/   owns get_tracked_doctypes() and its cache
          arc_one_tracked_doctype/

Behaviour belonging to a DocType lives on that DocType's controller; the event
handlers and endpoints stay thin and call into it. Shared concerns are factored
into `utils/` rather than repeated.

### Endpoints

All require the **System Manager** role, enforced by `utils.permissions.require_sync_role`.

| Method | Purpose |
|---|---|
| `arc_one_bridge.api.change_feed.changes(after, limit, doctypes)` | The feed. Returns `{cursor, has_more, changes[]}` ascending by cursor |
| `arc_one_bridge.api.change_feed.cursor_head()` | Newest cursor and rows retained, so a consumer can report its own lag |
| `arc_one_bridge.api.reconciliation.reconcile(doctype)` | Row count and newest `modified`, for drift detection |

### Configuration

**Arc One Sync Settings** (Single):

* **Record Changes** — master switch. Turning it off stops recording; the feed keeps
  serving what is already there.
* **Change Log Retention (days)** — pruned daily. Must comfortably exceed the longest
  expected consumer outage; a consumer whose cursor falls off the end of the log
  cannot catch up incrementally and needs a full re-sync.
* **Tracked DocTypes** — a Link table, not free text, so a typo cannot silently stop
  replicating a document type.

Adding a DocType does **not** backfill. Run a full sync from Arc-One afterwards.

### What this does not catch

`doc_events` only fire for writes that go through the ORM. `frappe.db.set_value`,
raw SQL and direct database edits do not fire them, and roughly 436 such call sites
exist in upstream `erpnext`/`hrms` alone.

**The feed is the low-latency path, not the correctness authority.** Arc-One pairs it
with a `modified` watermark sweep (which catches anything that bumped `modified`) and
nightly checksums (which catch the rest). `reconcile()` above exists for that second
layer.

Full reasoning: `audit/arc-one-autonomy-architecture.md` §5 and §8 in the Arc-One
repository, and `audit/2026-09-17-erpnext-integration-audit.md` INT-15.

### Installing

    bench --site <site> install-app arc_one_bridge
    bench --site <site> migrate

Then open **Arc One Sync Settings**, add the DocTypes to replicate, and run a full
sync from Arc-One to seed the replicas before relying on the feed.

#### License

MIT
