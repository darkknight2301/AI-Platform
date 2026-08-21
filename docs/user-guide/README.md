# User Guide

## Registration

Go to `/register`, provide a username, email, and password. Submitting
creates your account in `PENDING` status — you cannot sign in yet.
Self-registration can never grant you an elevated role; every account
starts as a plain `USER` (see `docs/adr/0006-registration-group-assignment-policy.md`).

## Approval

A Manager must approve your account before you can sign in. There's no
self-service way to skip this. If you try to log in while `PENDING`,
you'll see a message telling you approval is still pending — not a
generic login error. If you were rejected, logging in tells you that
specifically too. Contact whoever administers your organization's
account if you're stuck pending for an unreasonable time.

## Login

`/login` with your username or email and password. A wrong password
shows an error without revealing whether the username exists. After 5
failed attempts on the same account within 15 minutes, further
attempts (even with the correct password) are blocked for a period —
this is a brute-force protection, not a bug; wait and try again.

## Creating chats

Click **New chat** in the sidebar. Each chat is bound to one model,
chosen at creation (see "Selecting models" below) — the model a chat
uses can't be changed after messages exist in it (start a new chat to
switch models). Chats you delete are gone from your view, but their
history and audit trail aren't erased server-side (see the Owner Guide
for why).

## Selecting models

The model picker (top of the chat) lists every model an Owner has
enabled. Different models may be tuned for different things (e.g. a
coding-focused model vs. a general-purpose one) — pick whichever fits
what you're asking. Model availability is controlled centrally; if a
model you expect isn't listed, it may be disabled — ask an Owner.

## Prompt editing

Click **Edit prompt** on any of your messages to change what you
asked. Editing creates a new revision of that prompt and generates a
fresh reply — it does not overwrite history; the original version is
still reachable (see "Undo/redo" below).

## Undo/redo

After editing a prompt or regenerating a reply, a small revision
indicator (e.g. "2/2") appears next to that message. Use the
undo/redo arrows there to step between revisions — this switches which
version is currently shown, it does not delete any version. Undo/redo
applies per message slot, not to the whole conversation at once.

## History

Every message you've sent and every reply you've received is kept and
reloads automatically when you reopen a chat (including after a page
refresh) — nothing is client-side-only.

## Token quota

Your usage panel shows how much of your token quota you've used. Once
you hit your quota, new messages are rejected until it renews (ask
your Owner/Manager how your organization's renewal policy is
configured — either a rolling 24-hour window or a fixed daily reset;
see `docs/owner-guide/README.md`). Editing/regenerating a message
consumes quota the same as sending a new one, since each produces a
new model response.

## Chat limits

There's a cap on how many active (non-deleted) chats you can have at
once. Deleting an old chat frees up a slot. If you hit the limit,
creating a new chat is rejected with a clear error rather than failing
silently — try deleting a chat you no longer need.
