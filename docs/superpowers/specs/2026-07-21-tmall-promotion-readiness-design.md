# Tmall Promotion Readiness Design

## Goal

Reliably capture a Tmall product page's explicit promotional price and visible
activity labels after they have rendered, while retaining SKU matching as the
fallback source for pages that do not expose a labelled promotion.

## Evidence

On the authenticated T6magic product page, immediately after
`domcontentloaded`, the page body did not contain `平台加补后`、`超级立减`、
`首单礼金`、`店铺新客` or `活动价`. All five terms were present by three seconds
after `domcontentloaded` and remained present at ten seconds. The promotion
elements are still normal visible `SPAN` elements, so this is a render-timing
issue rather than a selector or wording change.

The existing collection path obtains the SKU initial-data price as soon as it
is available. That base price can be present before the promotional DOM is
rendered and currently replaces the earlier body-price candidate.

## Chosen Design

Add a promotion-price stability wait in `ProductCollector`.

1. After the page has been opened, read the body text repeatedly for up to the
   configurable deadline (default: 10 seconds; poll interval: 0.5 seconds).
2. A page is price-ready only when a recognised, labelled promotion price is
   present on two consecutive reads. Activity words never end price waiting.
3. If no stable labelled price appears before the deadline, continue with the
   final body text
   instead of failing the product. This preserves support for products that
   legitimately have no promotion.
4. When the settled text contains a labelled priority price, prefer that price
   over the SKU initial-data/base-price result. SKU matching remains enabled
   for model validation and remains the price fallback when no labelled
   promotion is visible.
5. Recognise activities from the same final settled body text, not from the initial
   post-navigation snapshot.
6. Log the settled promotion price, SKU/base price, readiness outcome and wait
   duration for each conflicting price decision. The log contains no cookies,
   credentials or page HTML.

## Price Priority

```text
explicit, visible labelled promotion price
    (平台加补后 / 店铺优惠后 / 补贴后 / 到手价 / 券后价 / 活动价)
    > SKU initial-data/base price for the matched model
    > ordinary unlabelled page price
    > existing historical fallback logic
```

Only labelled promotion prices take precedence. A generic `¥` value is not
elevated over a model-specific SKU value, so unrelated page prices cannot be
mistaken for the target model's price.

## Alternatives Considered

1. **Fixed 10-second sleep** — simple but slows every product and remains
   timing-dependent. Rejected.
2. **Add more activity keywords only** — does not help when even existing
   keywords have not rendered. Rejected.
3. **Stable labelled-price wait plus precedence** — does not let an early
   activity word end price collection, finishes promptly once the price region
   is stable, and retains a bounded fallback for pages without a promotion.
   Chosen.

## Testing

Add deterministic fake-page tests covering:

- a page whose promotional text appears only on a later body read;
- recognition of `超级立减` and `首单礼金` after the readiness wait;
- a labelled visible promotional price overriding an initial SKU base price;
- preservation of matched SKU/base price when no labelled promotion appears;
- timeout behavior that still returns a product result without an activity.

Run the focused collector and main-flow tests, then the project test suite.
Finally, repeat the authenticated T6magic browser probe and verify that the
captured body contains the promotion markers before the collector writes its
result.
