**Subject:** Feedback on Amortization Schedules and Standards

Dear Gabriel,

Many thanks for your detailed and thoughtful reply. I appreciate you sharing the timeline for BDT V2.0 and the ongoing collaboration with SWIFT to align with ISO 20022.

On the topic of amortization schedules, I would like to suggest that the **FpML standard**, which is maintained by ISDA, might be a logical solution to consider. FpML explicitly supports amortizing instruments by allowing changes in notional amounts to be expressed over time using the **`notionalStepSchedule`** element. This mechanism is widely used in the industry to capture stepwise reductions in principal, and could provide a useful reference point for extending BDT.

For illustration, here is a simplified FpML snippet:

```xml
<swapStream>
  <calculationPeriodAmount>
    <calculation>
      <notionalSchedule>
        <notionalStepSchedule>
          <step>
            <stepDate>2026-08-21</stepDate>
            <stepValue>1000000</stepValue>
          </step>
          <step>
            <stepDate>2027-08-21</stepDate>
            <stepValue>500000</stepValue>
          </step>
        </notionalStepSchedule>
      </notionalSchedule>
    </calculation>
  </calculationPeriodAmount>
</swapStream>
```

This structure clearly represents an amortizing notional, where the outstanding principal is reduced on scheduled dates.

For reference:

* FpML Specifications: [https://www.fpml.org/specifications](https://www.fpml.org/specifications)
* Documentation of `notionalStepSchedule`: [FpML 5.9 Notional Step Schedule](https://schemas.liquid-technologies.com/FpML/5.9/confirmation/notionalstepschedule.html)

As an additional alternative, the **ACTUS standard** (Algorithmic Contract Types Unified Standards) could also be relevant. ACTUS defines contract types algorithmically, so that once terms such as maturity, repayment rules, and interest are specified, the standard can automatically generate the entire amortization schedule. This approach is more computational than descriptive, but it has the advantage of consistency and transparency in how schedules are derived. More details can be found here: [https://www.actusfrf.org/](https://www.actusfrf.org/).

This combination of descriptive standards like FpML and algorithmic standards like ACTUS could provide useful reference points for enhancing BDT’s ability to cover amortizing instruments.

Thank you again for your openness to feedback, and I look forward to seeing how these developments evolve in the upcoming BDT release.

Best regards,
Ruben
