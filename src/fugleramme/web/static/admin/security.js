// The Security tab: how hard the admin password would be to guess, in the rough
// terms a person can act on: how many characters, out of how big an alphabet.
// Shown while typing only - the stored password never reaches the page, and the
// placeholder standing in for it would score as something it is not.

const password = document.querySelector("input[name=admin_password]");
const strength = document.getElementById("strength");
const [bar, caption] = [strength.querySelector("span"), strength.querySelector("small")];
const CLASSES = [[/[a-z]/, 26], [/[A-Z]/, 26], [/[0-9]/, 10], [/[^a-zA-Z0-9]/, 32]];
// Generous: counting the alphabet cannot tell a passphrase from a dictionary
// word, so the bands sit high enough that a guessable one does not read as safe.
const FULL = 80;  // the "strong" threshold, so a strong password reads as a full bar
const RATING = [
  [36, "weak", "guessable"],
  [60, "fair", "fine on a home network"],
  [FULL, "good", "holds up if the frame is exposed"],
  [Infinity, "strong", "hard to guess anywhere"],
];
password.addEventListener("input", () => {
  const typed = password.value;
  strength.hidden = !typed;
  if (!typed) {
    strength.className = "strength";  // nothing of the last rating left behind
    caption.textContent = "";
    return;
  }
  const alphabet = CLASSES.reduce((n, [cls, size]) => n + (cls.test(typed) ? size : 0), 0);
  const bits = typed.length * Math.log2(alphabet);
  const [, rating, caveat] = RATING.find(([ceiling]) => bits < ceiling);
  strength.className = "strength " + rating;
  bar.style.width = Math.min(100, (bits / FULL) * 100) + "%";
  caption.textContent = rating + " · " + caveat;
});
