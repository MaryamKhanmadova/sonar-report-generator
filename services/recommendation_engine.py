"""
Deterministic AI recommendation engine for SonarQube issues.

Generates developer-friendly recommendations and business impact assessments
based on rule keys, tags, issue types, and message patterns.  No external AI
APIs are used – all logic is rule-based and fully deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from models.issue import Issue, IssueType, Severity


# ---------------------------------------------------------------------------
# Priority & difficulty enums
# ---------------------------------------------------------------------------

class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


# ---------------------------------------------------------------------------
# Recommendation dataclass
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """
    A structured developer recommendation for a single issue.

    All fields are plain strings ready for direct insertion into reports.
    """

    priority: Priority
    difficulty: Difficulty
    estimated_time: str           # e.g. "5 min", "30 min", "1 hour"
    developer_recommendation: str  # plain-English WHY + HOW
    business_impact: str           # maintainability / performance / security impact
    sonar_url: str = ""           # filled in by caller with base URL


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RecommendationEngine:
    """
    Maps SonarQube issues to developer recommendations.

    The engine uses a tiered matching strategy:
    1. Rule key prefix / specific rule patterns
    2. Tags attached to the issue
    3. Issue type fallback
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recommend(self, issue: Issue, sonar_base_url: str = "") -> Recommendation:
        """
        Generate a :class:`Recommendation` for a single issue.

        Parameters
        ----------
        issue:
            The issue to analyse.
        sonar_base_url:
            Base URL used to build a direct link back to SonarQube.

        Returns
        -------
        Recommendation
        """
        rec = self._match_rule(issue)
        if not rec:
            rec = self._match_tags(issue)
        if not rec:
            rec = self._fallback(issue)

        # Decorate with SonarQube URL
        rec.sonar_url = (
            f"{sonar_base_url}/project/issues"
            f"?id={issue.project}&open={issue.key}"
        ) if sonar_base_url else ""

        return rec

    # ------------------------------------------------------------------
    # Rule-specific matching
    # ------------------------------------------------------------------

    def _match_rule(self, issue: Issue) -> Optional[Recommendation]:
        """Match against specific rule keys or prefixes."""
        rule = issue.rule.lower()
        msg = issue.message.lower()

        # ── Cognitive / Cyclomatic Complexity ──────────────────────────
        if "s3776" in rule or "cognitive" in msg:
            return Recommendation(
                priority=self._severity_to_priority(issue.severity),
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "This function has grown too complex for a human brain to reason about reliably. "
                    "Break it into smaller, focused helper functions — ideally one responsibility per function. "
                    "Apply the 'early return' pattern to eliminate deep nesting: validate inputs first and return "
                    "immediately on failure, keeping the happy path at the top level. "
                    "Each extracted function should be independently testable, which also improves coverage."
                ),
                business_impact=(
                    "HIGH maintainability impact: complex functions are 3–5× more likely to contain latent bugs "
                    "and take significantly longer to review in PRs. "
                    "MEDIUM regression risk: changes to tangled logic frequently cause unintended side effects."
                ),
            )

        # ── Nested functions / deep nesting ────────────────────────────
        if "s2004" in rule or "nest" in msg:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "Deeply nested functions make it hard to track scope and state. "
                    "Extract inner functions to module-level helpers or class methods. "
                    "Use dependency injection or callbacks to decouple the logic instead of nesting closures."
                ),
                business_impact=(
                    "HIGH maintainability impact: deeply nested code is difficult to unit-test in isolation. "
                    "MEDIUM regression risk: extracting nested functions could expose hidden bugs — add tests first."
                ),
            )

        # ── Array.sort without comparator ──────────────────────────────
        if "s2871" in rule or "localecompare" in msg:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "Calling `.sort()` on string arrays without a comparator uses byte-order comparison, "
                    "which produces incorrect results for accented characters (e.g., 'é' sorts after 'z'). "
                    "Replace with `.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))` "
                    "to get locale-aware alphabetic sorting that works correctly in all languages."
                ),
                business_impact=(
                    "HIGH reliability risk: incorrect sort order is a user-visible bug — data appearing in "
                    "wrong order in lists, dropdowns, and tables. "
                    "This is particularly impactful in international or multi-language applications."
                ),
            )

        # ── Nested ternary ─────────────────────────────────────────────
        if "s3358" in rule or "nested ternary" in msg:
            return Recommendation(
                priority=self._severity_to_priority(issue.severity),
                difficulty=Difficulty.EASY,
                estimated_time="10 min",
                developer_recommendation=(
                    "Nested ternary expressions are notoriously hard to read and debug. "
                    "Extract the inner condition into a named variable or a small helper function with a descriptive name. "
                    "This makes the intent explicit and the code self-documenting. "
                    "Example: instead of `a ? b ? x : y : z`, write `const inner = b ? x : y; return a ? inner : z;`"
                ),
                business_impact=(
                    "MEDIUM maintainability impact: reviewers and future maintainers will spend extra time deciphering intent. "
                    "LOW regression risk if extracted carefully."
                ),
            )

        # ── React JSX property naming ───────────────────────────────────
        if "s6747" in rule or "stroke-" in msg or "fill-rule" in msg or "clip-" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "JSX requires camelCase property names because it compiles to JavaScript object literals. "
                    "HTML attribute names like `stroke-width` must be written as `strokeWidth`, "
                    "`stroke-linecap` → `strokeLinecap`, `fill-rule` → `fillRule`, etc. "
                    "Most modern IDEs and the SonarQube quick-fix can auto-correct this. "
                    "Consider running `eslint --fix` with the `react/no-unknown-property` rule enabled."
                ),
                business_impact=(
                    "MEDIUM reliability risk: unknown properties are silently ignored by React, "
                    "meaning SVG styling may not render as intended in production. "
                    "LOW security risk but HIGH visual regression risk for icon-heavy UIs."
                ),
            )

        # ── Array index as key ─────────────────────────────────────────
        if "s6479" in rule or "array index" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.EASY,
                estimated_time="10 min",
                developer_recommendation=(
                    "Using array indices as React `key` props causes incorrect DOM reconciliation when the list "
                    "order changes (sort, filter, insert, delete). React uses keys to match existing DOM nodes "
                    "to new elements — a stable, unique key (e.g. an entity ID from your API) ensures animations, "
                    "input focus, and component state survive re-renders correctly. "
                    "If the data has no natural ID, generate a stable UUID on creation rather than at render time."
                ),
                business_impact=(
                    "MEDIUM reliability risk: subtle UI bugs such as wrong row being edited, animations glitching, "
                    "or stale form state appearing in the wrong list item. "
                    "LOW performance risk: React cannot optimise DOM diffing without stable keys."
                ),
            )

        # ── Non-native interactive element ─────────────────────────────
        if "s6848" in rule or "non-native interactive" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "Using a `div` with an `onClick` handler instead of a `<button>` or `<a>` creates "
                    "accessibility barriers: screen readers won't announce it as interactive, and it won't "
                    "receive keyboard focus by default. Replace with the appropriate semantic HTML element. "
                    "If the design requires a custom appearance, style a `<button>` with CSS instead."
                ),
                business_impact=(
                    "MEDIUM reliability impact: users who navigate by keyboard or assistive technology "
                    "cannot interact with the element, potentially blocking core features. "
                    "MEDIUM legal risk in jurisdictions where WCAG compliance is mandated (e.g. EU Web Accessibility Directive)."
                ),
            )

        # ── dialog / listbox / status ARIA roles ───────────────────────
        if "s6819" in rule or "dialog" in msg or "listbox" in msg or "presentation" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "The ARIA `role` attribute should only be used when no suitable native HTML element exists. "
                    "Native elements carry implicit semantics, keyboard interactions, and assistive-technology "
                    "announcements for free. Use `<dialog>` instead of `role='dialog'`, "
                    "`<select>` instead of `role='listbox'`, `<output>` instead of `role='status'`, etc. "
                    "Native elements also receive future browser improvements automatically."
                ),
                business_impact=(
                    "MEDIUM maintainability impact: ARIA polyfills add code complexity and can break with library updates. "
                    "MEDIUM accessibility impact: users on screen readers may not receive correct announcements."
                ),
            )

        # ── void operator ──────────────────────────────────────────────
        if "s3735" in rule or "void" in msg:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "The `void` operator discards the return value of an expression. In modern TypeScript/JavaScript, "
                    "this is almost always a sign that you have a floating Promise that is not being awaited or handled. "
                    "Replace `void someAsyncFn()` with either `await someAsyncFn()` (inside an async function) "
                    "or add explicit `.catch()` error handling. Silently dropped Promises hide errors in production."
                ),
                business_impact=(
                    "HIGH reliability risk: unhandled Promise rejections are swallowed silently, "
                    "meaning errors go unlogged and users see stale UI without explanation. "
                    "MEDIUM security risk if the discarded Promise performs authentication or authorization."
                ),
            )

        # ── Optional chaining preference ────────────────────────────────
        if "s6582" in rule or "optional chain" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "Replace `obj && obj.prop` with `obj?.prop` (optional chaining). "
                    "This is not just a style preference — it also correctly handles `null`, `undefined`, "
                    "and `0` / `false` / empty-string values on the left side without accidentally short-circuiting. "
                    "Modern TypeScript and the SonarQube quick-fix can apply this automatically."
                ),
                business_impact=(
                    "LOW maintainability impact: cleaner code that is easier to scan. "
                    "LOW bug risk: `&&` short-circuits on any falsy value (0, false, ''), "
                    "which may not be the intended behaviour."
                ),
            )

        # ── Deprecated API ─────────────────────────────────────────────
        if "s1874" in rule or "deprecated" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="15 min",
                developer_recommendation=(
                    "This API is marked as deprecated, which means the library authors have signalled "
                    "intent to remove it in a future major version. Check the library changelog and migration guide "
                    "to find the recommended replacement. Migrating now avoids a breaking change during a future upgrade "
                    "when you may be under time pressure. Add a code comment linking to the migration guide if "
                    "the fix requires larger refactoring."
                ),
                business_impact=(
                    "MEDIUM maintainability risk: deprecated APIs are removed in major version bumps, "
                    "which can block dependency upgrades and security patches. "
                    "LOW immediate risk but compounds over time as the library diverges."
                ),
            )

        # ── Unnecessary escape character ────────────────────────────────
        if "s6535" in rule or "unnecessary escape" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="2 min",
                developer_recommendation=(
                    "Unnecessary escape characters (`\\(`, `\\)`, `\\+` outside a character class) "
                    "add visual noise and can confuse readers about the actual pattern intent. "
                    "In JavaScript RegExp literals, only a specific set of characters need escaping outside `[]`. "
                    "Remove the backslashes or use a raw string test with `.test()` instead."
                ),
                business_impact=(
                    "LOW maintainability impact: minor readability issue. "
                    "LOW correctness risk in most cases, though incorrect regex understanding can lead to validation bypasses."
                ),
            )

        # ── Nullish coalescing assignment ───────────────────────────────
        if "s6606" in rule or "nullish" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "Replace `if (x === null || x === undefined) x = value;` with `x ??= value;` "
                    "(nullish coalescing assignment). This is semantically equivalent but more concise. "
                    "Unlike `||=`, it only assigns when the left side is `null` or `undefined`, "
                    "not when it is `0`, `false`, or `''`."
                ),
                business_impact=(
                    "LOW maintainability impact: cleaner, more idiomatic modern JavaScript. "
                    "No runtime performance difference."
                ),
            )

        # ── Set for includes check ──────────────────────────────────────
        if "s7776" in rule or "set" in msg and "includes" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "When an array is used only to check membership (`array.includes(value)`), "
                    "convert it to a `Set` and use `set.has(value)` instead. "
                    "Set lookups are O(1) versus Array.includes which is O(n). "
                    "For small arrays the difference is negligible, but it signals intent clearly "
                    "and scales better if the array grows."
                ),
                business_impact=(
                    "LOW performance impact for small arrays; MEDIUM for large data sets. "
                    "MEDIUM maintainability: communicates clearly that this data structure is used for membership tests."
                ),
            )

        # ── CSS missing scoping root ────────────────────────────────────
        if "s8776" in rule or "scoping root" in msg:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.MEDIUM,
                estimated_time="20 min",
                developer_recommendation=(
                    "A CSS rule inside a mixin or SCSS file is missing its scoping root selector. "
                    "Without proper scoping, styles can leak out and affect unrelated elements globally. "
                    "Wrap the rule in an appropriate parent selector (e.g. `.component { & { ... } }`) "
                    "or use CSS Modules / BEM naming to prevent leakage."
                ),
                business_impact=(
                    "HIGH reliability risk: unscoped styles can break layout on unrelated pages. "
                    "Regression risk is high in large codebases where CSS is shared across components."
                ),
            )

        # ── Invalid CSS import position ─────────────────────────────────
        if "s8778" in rule or "position for @import" in msg:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "@import rules must appear at the top of a CSS/SCSS file, before any other rules. "
                    "An @import after a rule is ignored by some browsers, causing fonts, variables, or "
                    "utility classes to not load. Move all @import statements to the very beginning of the file."
                ),
                business_impact=(
                    "HIGH reliability risk: fonts or shared variables may silently fail to load in production, "
                    "causing visual regressions that are hard to reproduce."
                ),
            )

        # ── Keyboard listener accessibility ─────────────────────────────
        if "s1082" in rule or "keyboard listener" in msg:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="15 min",
                developer_recommendation=(
                    "A visible, non-interactive element has an `onClick` handler but no keyboard equivalent. "
                    "Add `onKeyDown` or `onKeyUp` handlers that respond to Enter and Space keys, "
                    "and add `tabIndex={0}` so the element is keyboard-focusable. "
                    "Better yet, replace the element with a semantic `<button>` which handles all of this natively."
                ),
                business_impact=(
                    "MEDIUM accessibility impact: keyboard-only users and switch-access device users "
                    "cannot activate this element. MEDIUM legal risk in accessibility-regulated sectors."
                ),
            )

        # ── Re-export pattern ───────────────────────────────────────────
        if "s7763" in rule or "re-export" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="2 min",
                developer_recommendation=(
                    "Replace `import { X } from './module'; export { X };` with "
                    "`export { X } from './module';` (export…from). "
                    "This is more concise, makes the barrel export pattern explicit, "
                    "and avoids importing the symbol into the current module's scope unnecessarily."
                ),
                business_impact=(
                    "LOW maintainability impact: cleaner index files. "
                    "Potential tree-shaking improvement in some bundlers."
                ),
            )

        # ── Nested template literals ────────────────────────────────────
        if "s4624" in rule or "nested template" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="10 min",
                developer_recommendation=(
                    "Nested template literals (`\\`outer \\`inner\\` more\\``) are hard to read and "
                    "error-prone due to backtick escaping. Extract the inner expression into a named "
                    "constant before the template literal: `const inner = \\`...\\`; const result = \\`outer ${inner} more\\`;`"
                ),
                business_impact=(
                    "LOW maintainability impact: readability issue that slows down code reviews."
                ),
            )

        # ── Prefer .at() ───────────────────────────────────────────────
        if "s7755" in rule or ".at(" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="2 min",
                developer_recommendation=(
                    "Replace `arr[arr.length - 1]` with `arr.at(-1)`. "
                    "The `.at()` method is more readable, handles negative indices elegantly, "
                    "and avoids an off-by-one risk when computing the index manually. "
                    "It is supported in all modern browsers and Node.js 16+."
                ),
                business_impact=(
                    "LOW maintainability impact: cleaner idiom. No performance difference."
                ),
            )

        # ── Prefer Number.parseFloat ────────────────────────────────────
        if "s7773" in rule or "parsefloat" in msg:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="2 min",
                developer_recommendation=(
                    "Replace the global `parseFloat()` with `Number.parseFloat()`. "
                    "The global function is a legacy API; the module-scoped version is identical in behaviour "
                    "but makes it explicit that you are using the ES2015+ Number method, "
                    "which is preferred in strict codebases."
                ),
                business_impact=(
                    "LOW maintainability impact: code consistency and linter compliance."
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Tag-based matching
    # ------------------------------------------------------------------

    def _match_tags(self, issue: Issue) -> Optional[Recommendation]:
        """Match recommendations based on issue tags."""
        tags = set(t.lower() for t in issue.tags)

        if "accessibility" in tags:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "This issue violates Web Content Accessibility Guidelines (WCAG). "
                    "Accessibility fixes improve the experience for users with disabilities, "
                    "including screen reader users, keyboard navigators, and users with motor impairments. "
                    "Consult the ARIA specification and the React accessibility docs to apply the correct "
                    "semantic fix rather than adding ARIA attributes as an afterthought."
                ),
                business_impact=(
                    "MEDIUM legal risk in the EU (Web Accessibility Directive), US (ADA), and other jurisdictions. "
                    "MEDIUM reputation risk — accessibility issues are frequently discovered by automated audits."
                ),
            )

        if "brain-overload" in tags:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.MEDIUM,
                estimated_time="1 hour",
                developer_recommendation=(
                    "This code has exceeded the complexity threshold that humans can reliably reason about. "
                    "Divide and conquer: identify the distinct responsibilities in this block and extract "
                    "each into a named function. Each function should do one thing and have a name that "
                    "makes the code read like documentation."
                ),
                business_impact=(
                    "HIGH maintainability impact: complex code significantly increases time-to-review and "
                    "new-developer onboarding cost. HIGH regression risk on every future change."
                ),
            )

        if "performance" in tags:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.EASY,
                estimated_time="15 min",
                developer_recommendation=(
                    "This pattern has a known performance issue. "
                    "Profile the affected code path to confirm the impact, then apply the "
                    "recommended optimisation. Use browser DevTools Performance panel or "
                    "React Profiler to measure before and after."
                ),
                business_impact=(
                    "MEDIUM performance impact depending on call frequency. "
                    "In hot render paths this can cause noticeable UI jank."
                ),
            )

        if "obsolete" in tags:
            return Recommendation(
                priority=Priority.MEDIUM,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "Replace this deprecated API with its modern equivalent. "
                    "Check the library release notes and migration guide. "
                    "Sticking with deprecated APIs makes future upgrades riskier "
                    "and can block adoption of security patches."
                ),
                business_impact=(
                    "MEDIUM maintenance risk: deprecated APIs are removed in major version bumps, "
                    "which can block dependency upgrades and security patches."
                ),
            )

        if "unused" in tags:
            return Recommendation(
                priority=Priority.LOW,
                difficulty=Difficulty.EASY,
                estimated_time="5 min",
                developer_recommendation=(
                    "Remove dead code. Unused variables, imports, and commented-out code "
                    "add noise that makes the codebase harder to navigate. "
                    "If the code is preserved intentionally as a reference, "
                    "move it to a comment in the git history instead and delete it from the source."
                ),
                business_impact=(
                    "LOW impact individually, but dead code accumulates and significantly increases "
                    "the cognitive load of understanding the codebase over time."
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback(self, issue: Issue) -> Recommendation:
        """Generic recommendation based on issue type."""
        if issue.issue_type == IssueType.BUG:
            return Recommendation(
                priority=Priority.HIGH,
                difficulty=Difficulty.MEDIUM,
                estimated_time="30 min",
                developer_recommendation=(
                    "This is a confirmed bug — incorrect runtime behaviour that needs a targeted fix. "
                    "Write a failing unit test that reproduces the bug first, then fix the code until "
                    "the test passes. This ensures the bug cannot regress silently."
                ),
                business_impact=(
                    "HIGH reliability risk: bugs produce incorrect behaviour for end users. "
                    "Fix before next release."
                ),
            )

        if issue.issue_type == IssueType.VULNERABILITY:
            return Recommendation(
                priority=Priority.CRITICAL,
                difficulty=Difficulty.HARD,
                estimated_time="2 hours",
                developer_recommendation=(
                    "This is a security vulnerability. Treat it with urgency: "
                    "review the OWASP guidance for this vulnerability class, "
                    "apply the fix in a dedicated security patch, "
                    "and consider whether the vulnerability is exploitable in the current deployment. "
                    "Notify your security team if the severity is high."
                ),
                business_impact=(
                    "CRITICAL security impact. Vulnerabilities can lead to data breaches, "
                    "account takeovers, or regulatory fines. "
                    "Prioritise immediately."
                ),
            )

        # Default code smell
        sev = issue.severity
        priority = self._severity_to_priority(sev)
        time_map = {
            Priority.CRITICAL: "1 hour",
            Priority.HIGH: "30 min",
            Priority.MEDIUM: "15 min",
            Priority.LOW: "5 min",
        }

        return Recommendation(
            priority=priority,
            difficulty=Difficulty.EASY,
            estimated_time=time_map.get(priority, "15 min"),
            developer_recommendation=(
                "Review the SonarQube rule description for the specific fix guidance. "
                "Code smells reduce readability and maintainability even when they do not "
                "cause runtime errors. Fixing them now prevents compounding technical debt."
            ),
            business_impact=(
                "MEDIUM maintainability impact: code smells slow down future development and "
                "increase the cost of every code change in the affected file."
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _severity_to_priority(severity: "Severity") -> Priority:
        from models.issue import Severity as S
        return {
            S.BLOCKER: Priority.CRITICAL,
            S.CRITICAL: Priority.HIGH,
            S.MAJOR: Priority.MEDIUM,
            S.MINOR: Priority.LOW,
            S.INFO: Priority.LOW,
        }.get(severity, Priority.LOW)
