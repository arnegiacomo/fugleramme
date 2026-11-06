// The admin's script, a module per section. Each sets itself up as it is
// imported; what has to wait for all of them is called here.
import "./page.js";
import "./settings.js";
import "./detector.js";
import "./security.js";
import "./system.js";
import {restoreScroll, track} from "./forms.js";
import {start} from "./preview.js";

// After settings.js has dimmed the fields its mode ignores, or the snapshot
// would count them and a round trip back to the saved state would be a change.
track();
start();
restoreScroll();
