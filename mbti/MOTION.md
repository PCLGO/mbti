# MBTI Motion Notes

Source checked with local Scrapling project against https://www.16personalities.com/free-personality-test.

## Confirmed Static Asset Evidence

Scrapling found the test-specific CSS asset:

- https://www.16personalities.com/build/assets/personality-test.CJ9G5Ffe.css

The only explicit test-specific motion rule exposed there is the progress filler:

```css
main.q-pt .progress-wrapper .progress-bar .filler {
  transition: all .2s ease-in-out;
}
```

The broader core stylesheet includes utility animations such as fade-in, slide-up, pulse, and cubic-bezier helpers, but the public static assets do not expose a complete questionnaire transition state machine.

## Local Implementation

Applied to `mbti/index.html`:

- Progress fill: `width .2s ease-in-out`.
- Question cards do not use opacity entrance animation. The active/inactive opacity is applied immediately on render so page changes never flash all questions at full opacity.
- Question state transition: `opacity .2s cubic-bezier(.4,0,.2,1)`, matching the measured 16Personalities fieldset opacity transition.
- Active question: opacity 1, no transform.
- Answered inactive question: opacity .3.
- Pending inactive question: opacity .3.
- Focus rule: first-time sequential answering advances to the next unanswered question; editing an already answered question keeps that edited question active and dims every other visible question, including later answered questions.
- Step navigation: top `Previous step`, bottom centered `Next step`, following the interaction rhythm of the 16Personalities questionnaire while keeping local styling.
- Choice sizes on desktop: `70 / 56 / 42 / 56 / 70`, matching the large-circle rhythm from the audited 16Personalities layout while keeping this app's five-option scale.
- Choice hover: `translateY(-1px)` over 160ms.
- Choice selected: `choicePop .18s cubic-bezier(.2,.8,.2,1)`.
- Result sections: `resultIn .42s cubic-bezier(.22,1,.36,1) both` with section-level delays.
- Reduced-motion media query disables animations and transitions.

## Playwright Audit

Local Playwright/Chrome verification artifacts are stored in `screenshots/motion-audit/`.

Measured 16Personalities questionnaire behavior:

- First visible question: opacity `1`.
- Inactive visible questions: opacity `0.3`.
- Fieldset transition: `opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1)`.
- Largest circle: `70px`.
- Second circle: `56px`.
- Radio tick transition: `0.2s ease-in-out`.

Measured local behavior after implementation:

- Answered inactive card: opacity `0.3`.
- Current pending card: opacity `1`.
- Future pending cards: opacity `0.3`.
- Card transition: `opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1)`.
- Desktop choice sizes: `70px`, `56px`, `42px`, `56px`, `70px`.

Goal: interaction-level parity, not visual/source parity.
