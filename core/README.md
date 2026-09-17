# donewise-harness

Independent MIT package containing DoneWise contracts, not a running harness.
Requires Python 3.12 or later and Pydantic v2.

```python
from donewise_harness.contracts import Action, Outcome, claims_for, may_claim_success

assert may_claim_success(Outcome.VERIFIED)
claims = claims_for(Outcome.VERIFIED, Action.PAYMENT_CHARGE)
```

`Receipt` rejects claims that contradict its outcome and action.
Only VERIFIED permits a success claim.
NEEDS_APPROVAL and REJECTED require zero writes.
Calendar and payment targets remain distinct typed objects.
Timestamps require offsets and normalize to UTC; display uses the IANA zone.
Official `tzdata` provides IANA timezone data on Windows through `zoneinfo`.
`ports` defines adapter and fault-injector protocols without implementations.
`spoken.render_spoken` renders receipt data without calling a provider or model.
Policy validation alone does not prove an external effect; the future harness must.
