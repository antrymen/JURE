# Third-party sources and retained historical limitations

Checked 2026-11-15. These notices supplement historical records; scientific values and private historical originals remain unchanged. Nine public excerpt fields have been omitted and public hashes updated with an explicit mapping in evidence/PUBLIC_EXPORT_TRANSFORMS.json. MIT selection applies only to author-owned software after authorization, not third-party materials.

## Replogle / scPerturb data

Source dataset: Joseph Replogle and Jonathan Weissman (2022), processed Perturb-seq datasets, https://doi.org/10.25452/figshare.plus.20029387 ; original study https://doi.org/10.1016/j.cell.2022.05.013 . The official Figshare API record explicitly specifies CC BY 4.0: https://api.figshare.com/v2/articles/20029387 .

Harmonized files: Stefan Peidli and colleagues, scPerturb Single-Cell Perturbation Data, version 1.4, https://doi.org/10.5281/zenodo.13350497 ; associated study https://doi.org/10.1038/s41592-023-02144-y . Official API metadata specifies CC BY 4.0: https://zenodo.org/api/records/13350497 .

License: https://creativecommons.org/licenses/by/4.0/ . JURE transforms counts into binary detection states, selects joint states, computes aggregate perturbation statistics and validation results, and stores selected guide metadata. These are JURE-derived analyses, not unchanged source datasets or source-author-endorsed results. Raw H5AD files are not bundled.

| File | Official MD5 |
|---|---|
| ReplogleWeissman2022_K562_essential.h5ad | d8cba17576d1a8afc0f7d71b79cad0f7 |
| ReplogleWeissman2022_K562_gwps.h5ad | 13db594f8f1d2ccb88fec44a13e414dc |

## External text checked for retention

The following source texts carry CC BY 4.0. Historical evidence sentences in the SUPT5H, M03-HSPA9 and RIOK1 cases are short analytical summaries rather than whole sentences matched in the checked full text. This comparison is not proof of how the original model generated them. EIF2B3 contains an abbreviated passage from eLife 65703 and a title from eLife 76171. Preserve source attribution and indicate the abbreviation/summary; do not relicense source expression under MIT.

- Diamant Gil, Bahat Anat, Dikstein Rivka. The elongation factor Spt5 facilitates transcription initiation for rapid induction of inflammatory-response genes. https://doi.org/10.1038/ncomms11547 . CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ .
- Butler Christopher, Dunmire Morgan, Choi Jaebok, Szalai Gabor, Johnson Anissa, Lei Wei, Chen Xin, Liu Liang, Li Wei, Walter Matthew J, Liu Tuoen. HSPA9 /mortalin inhibition disrupts erythroid maturation through a  TP53 -dependent mechanism in human CD34+ hematopoietic progenitor cells. https://doi.org/10.1016/j.cstres.2024.03.006 . CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ .
- Smurova Ksenia, Damizia Michela, Irene Carmela, Stancari Stefania, Berto Giovanna, Perticari Giulia, Iacovella Maria Giuseppina, D’Ambrosio Ilaria, Giubettini Maria, Philippe Réginald, Baggio Chiara, Callegaro Elisabetta, Casagranda Andrea, Corsini Alessandro, Polese Vincenzo Gentile, Ricci Anna, Dassi Erik, De Wulf Peter. Rio1 downregulates centromeric RNA levels to promote the timely assembly of structurally fit kinetochores. https://doi.org/10.1038/s41467-023-38920-9 . CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ .
- Schoof Michael, Boone Morgane, Wang Lan, Lawrence Rosalie, Frost Adam, Walter Peter, Sonenberg Nahum, Pfeffer Suzanne R. eIF2B conformation and assembly state regulate the integrated stress response. https://doi.org/10.7554/eLife.65703 . CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ .
- Boone Morgane, Wang Lan, Lawrence Rosalie E, Frost Adam, Walter Peter, Schoof Michael, Sonenberg Nahum, Pfeffer Suzanne R. A point mutation in the nucleotide exchange factor eIF2B constitutively activates the integrated stress response by allosteric modulation. https://doi.org/10.7554/eLife.76171 . CC BY 4.0; https://creativecommons.org/licenses/by/4.0/ .

The second EIF2B3 string is exactly the bibliographic title of Chen et al., Brain and Development (2016), https://doi.org/10.1016/j.braindev.2015.11.002 (PMID 26625702). It is retained as title identification, not as a grant to reproduce that article.

## Historical source locators

HISTORICAL_SOURCE_LOCATORS.json restores the source URLs/identifiers for TIMM23B and SAMM50 from their original web records. Each historical source file SHA256 matches the reference in the existing follow-up record. Original gene/literature SOURCE_ERROR records remain failures; a later web-based follow-up is a separate evidence acquisition route. Full web responses and their additional quotations are not added to this candidate.

## Known historical error and outstanding decisions

Additional10 M04_03 MED30 cites PMC11100879 (https://doi.org/10.21203/rs.3.rs-4326418/v1), a preprint version. Its historical description of human glioma cells is not supported by the cited full text, which includes pancreatic cancer/Mia PaCa-2 experiments. The source carries CC BY 4.0, but this does not validate the erroneous model description. Keep this record as historical Agent output with this notice, not as verified biological evidence.

Additional10 M04_02 INTS2 cites https://doi.org/10.1016/j.celrep.2020.107917 under CC BY-NC-ND 4.0. Its uncertain evidence_excerpt has now been omitted from the public derivative; the citation and historical analysis remain. Source expression is not relicensed under MIT.

The evidence_excerpt fields for EIF2S1, PHB2, M02-RPL24, TSR2 and M05-RPL24, together with the INTS2 field above and three repeated copies in executed_source files, are excluded: nine fields total. See evidence/PUBLIC_EXPORT_TRANSFORMS.json. Original historical records remain private and unchanged. This is a targeted content exclusion, not a claim that permissions for those omitted passages were obtained.
