BDT v1.2 Release Notes:

1. Added a new Series type with attributes for number, amount and product.
2. Added a new Tranche type with attributes for number, amount and product.
3. Added enumeration, Uncertificated Registered to FormOfNote.
4. Added new indentifier enumerations, CMU, FIGI, SEDOL, VALOR.
5. Added Cacluation Amount.
6. Added Early Redemption Amount.
7. Added Change of Interest/Payment Basis.
8. Added Indication of Interest.
9. Added Use of Proceeds and Gross Proceeds.
10. Added Redemption Payment Basis.
11. Added DLT Platform Information covering: Type, Accessibility, Role, Fee, Name, Identifier, TokenType, Token TechnicalReference, TokenTechnicalReferenceID, Smart Contract.
12. Added additional partyRoles: Registrar, Custodian, Platform Operator, Direct Participant, Deposit Bank, Joint Global Coordinator, Joint Bookrunner, Market Practice Advisor, Transfer Agent, Issue Agent, Cash Token Manager, Legal Advisor, Paying Agent, Lodging Agent, Central Account Keeper, Tokenisation Registrar, Crypto Securities Registrar.
13. Added free text field for partyRoleOtherType.
14. Changed cardinality of Listing element from maxOccurs="1" to maxOccurs="unbounded".
15. Changed cardinality Documentation element from maxOccurs="1" to maxOccurs="0".
16. Changed OptionalRedemption to a complex type that includes OptionalRedemptionDate and OptionalRedemptionAmount.
17. Changed AmountWithType from xs:choice to xs:sequence.
18. Chnaged cardinality of ClearingSettlementSystem from minOccurs="1" to minOccurs="0".
19. Added INDEX_LINKED_INTEREST value to InterestType enumeration.