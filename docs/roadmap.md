# Remaining acceptance and follow-on work

The core source implementation is not a production acceptance claim. Track these separately:

1. Configure and authenticate Pi on the actual control machine, with scoped workspace/model access
2. Run OpenCode and the Go node on actual native Windows, not WSL or a cross-build substitute
3. Deploy Host/protected application proxy through the existing approved production route without disturbing other services
4. Complete a user-approved tiny real coding task, test/artifact evidence, same-Pi result reporting and cancellation/reconnect/duplicate-submission acceptance
5. Complete desktop and narrow-screen UI checks against the existing private application

Existing requested follow-ons remain in scope; they have not been cancelled:

- `awf update --all`: implement a bounded, explicit update workflow for the installed Host/node/Pi/OpenCode versions, with source/version checks, rollback planning and applicable confirmation gates. The current CLI returns an explicit not-implemented error and changes nothing
- Authorized serial plan advancement: retain per-task identity/budgets and explicit plan-level authorization; queue the next task only after verified prior completion and within the same authorization. Current core rejects a second concurrent project execution instead of inventing automatic permission

Any decision to remove these from a planned release requires an explicit scope decision. Do not present this roadmap as completion of those features.
