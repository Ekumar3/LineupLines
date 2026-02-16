# LineupLines - AI Context & Important Notes

## ADP Delta Sign Convention (CRITICAL)

**This is the most important concept to understand:**

- **ADP (Average Draft Position)** = Lower numbers are BETTER players (expected to go early)
- **Pick number** = Your draft position (lower = earlier in draft)

### Correct Interpretation:
- **Positive delta** (picked LATER than ADP) = **GOOD ✅ (Green)**
  - Example: Player has ADP 15, you picked them at position 20 → delta = +5 → Good value!
  - You got a great player (low ADP) later than they normally go

- **Negative delta** (picked EARLIER than ADP) = **BAD ❌ (Red)**
  - Example: Player has ADP 25, you picked them at position 15 → delta = -10 → Bad value/Reach
  - You reached for a player who shouldn't have been picked that early

### Color Coding:
- 🟢 **Green**: delta > 0 (picked later, got value)
- 🔴 **Red**: delta < 0 (picked earlier, reached)

This applies to ALL frontend display of ADP deltas in the roster view.
