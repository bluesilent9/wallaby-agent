# Build 50: archive drive discovery survives refreshes

Both read and write selectors call the same protected disc.drives inventory, which reads sysfs and does not open the medium. The read selector previously stored discovered options only in its current DOM element. Rebuilding Disc Operations discarded those options. If the asynchronous response arrived after a rebuild, it populated a detached element instead of the visible selector.

The reader now retains the discovered drive list and selected path in page state. New selectors inherit them. A discovery response updates that state and renders the current view, even if the original selector was replaced. A refreshed inventory that no longer contains the selected drive clears that selection.

The running burn/verification job uses its private fixed device path and reports outcomes through workspace state. It never uses the read selector. Read and disc-status commands remain unavailable during active optical operations. Listing drives reads sysfs only.

The UI regression deliberately rebuilds the page while discovery is in flight, then verifies the returned drive appears in the current selector and its selection survives a verification-to-complete transition. All 20 interface suites pass. Backend and optical verification code are unchanged from Build 49's 154-check regression and real three-Agent recovery validation.

Finish the current protected session before installing this package. The session-specific Build 47 recovery helper continues its existing read-back without requiring this update.
