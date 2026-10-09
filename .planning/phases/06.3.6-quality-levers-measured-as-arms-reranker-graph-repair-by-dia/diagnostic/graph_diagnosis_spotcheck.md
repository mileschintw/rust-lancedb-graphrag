# Graph diagnosis spot-check sample (D-137)

Seed 42; 2 rows per class; read from the table only.

## alias_split (0 questions)

## absent (3 questions)

### mhr-02989530f5ad

- question: Considering the information from an article in The Economic Times and another in The Times of India about Malini Goyal, which city does she mention as having a significant impact on her career, and is also the location where a conference she attended took place?
- mentions: ["The Economic Times", "Economic Times", "The Times of India", "Times of India", "Malini Goyal"]
- label: absent
- memberships: absent
- gold_chunk_ids: 
- seed_entity_ids: 20ef83e3-b70f-4a53-bf6a-b6295a1ef1ec, 551bb18f-075b-4076-84d1-43264718adec, 8b130a9e-56ec-4b71-a1b5-c00867266ca2, bfc8ee81-8bf4-48b2-93ba-3aa9d18d4d85, 3e2c7461-dc65-4831-ae01-e5d05412f57c, 04b675e6-91cc-4ebd-b6b2-8851a4ec78af
- alias_entity_ids: 

### mhr-dd03ecc9ba3d

- question: Considering the information from a BBC article detailing the new traffic management plan in Indiranagar and a Times of India report on the recent zoning regulations affecting businesses in the same area, which single character from the English alphabet is common to the official abbreviations for both the traffic authority responsible for implementing the management plan and the municipal department enforcing the zoning regulations?
- mentions: ["BBC", "Indiranagar", "Times of India", "English"]
- label: absent
- memberships: absent
- gold_chunk_ids: 
- seed_entity_ids: 458336ab-2fd8-4913-ad63-d1e01fe66c67, 3758ed10-34b3-43f3-b331-1fd63718af2b, aeb00842-407b-409f-ad79-85027b642555, 04b675e6-91cc-4ebd-b6b2-8851a4ec78af, ffc1ca71-7aeb-4356-ad68-6fdab461b37e
- alias_entity_ids: 

## missing_edge (15 questions)

### mhr-0085f76defbe

- question: Does the Engadget article claim that CyberGhost's cybersecurity measures include an independent security audit, a vulnerability disclosure program, and transparency reporting, while the TechCrunch article suggests that Keep Labs employs automated tools for code vulnerability assessments, indicating different approaches to product security?
- mentions: ["Engadget", "CyberGhost", "TechCrunch", "Keep Labs"]
- label: missing_edge
- memberships: missing_edge
- gold_chunk_ids: 01070ac6-0fc0-464d-9f1f-756573b99c0e:62, 1e7b3e87-c1c9-4556-b00a-405525057b55:30
- seed_entity_ids: d8565a3c-08ef-4829-8580-9eb828973280, 6c3d50d8-9138-4094-85ee-8de5669aedcc, a62b6aa2-0ff2-4d10-96ef-5fd53f9a3243, f4b6b43f-1506-4c71-8f6c-58017ddca410
- alias_entity_ids: 

### mhr-d7aaad823d49

- question: Does the TechCrunch article suggest that social networks are controlled by large corporations in a similar way to how The Age article implies that DeepMind was a target for acquisition by major tech companies?
- mentions: ["TechCrunch", "The Age", "Age", "DeepMind"]
- label: missing_edge
- memberships: missing_edge
- gold_chunk_ids: 26edd300-330b-4cdc-b858-34d44f6c4042:30, 63cc6908-2129-4f07-97b1-8b4b3a0c18c5:2
- seed_entity_ids: 21a38c76-fc01-4b49-bf18-fbfdd03bb5cf, 37476820-85ca-40e5-a2e8-98153cd16a56, 0f9a2b95-02e2-47ee-ae6c-3802f5ad3343, f4b6b43f-1506-4c71-8f6c-58017ddca410
- alias_entity_ids: 

## other (20 questions)

### mhr-434e7d85190f

- question: Considering the information from an article in The New York Times about David Sutter's philanthropic efforts and a piece from The Guardian discussing his recent investments in technology startups, which city, beginning with the letter 'S', is both the location of the charity event he sponsored and the headquarters of the startup he invested in that is pioneering artificial intelligence research?
- mentions: ["The New York Times", "New York Times", "David Sutter", "The Guardian", "Guardian"]
- label: other
- memberships: other
- gold_chunk_ids: 
- seed_entity_ids: c8177e93-d9ed-4b92-a508-dec4007f717c, 0a6804e0-b3e7-4eed-b45d-3ac55b1d9d7d, 9c4a7742-c744-489b-a729-59ef3ce89835
- alias_entity_ids: 

### mhr-54a88d9a188f

- question: Between the TechCrunch report on Sam Bankman-Fried published on October 2, 2023, and the Fortune report on Sam Bankman-Fried published on October 4, 2023, was there consistency in the portrayal of Sam Bankman-Fried's involvement in fraudulent activities?
- mentions: ["TechCrunch", "Sam Bankman-Fried", "October", "Fortune"]
- label: other
- memberships: other
- gold_chunk_ids: 4ad73812-336a-47f2-9ac7-860dcd4f5da5:21, 728187d6-09c3-434f-9353-2b3ecb364408:1, fbe98246-6fd5-4dd5-9b99-a6eb4f0f4f93:7
- seed_entity_ids: c5b3b336-6764-4aa6-9397-798fc4bc62c3, 7773be75-1b2c-4033-953f-d4638f049f5c, 90641223-dc72-4000-8571-9caccda39410, f4b6b43f-1506-4c71-8f6c-58017ddca410
- alias_entity_ids: 
