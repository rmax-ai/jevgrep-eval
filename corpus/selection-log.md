# Frozen selection flow

Registry: operator-frozen candidate registry; outcomes were not used to invent candidates.

## Quotas

- dev target: at least 12 tasks; three complete Python repositories are assigned.
- holdout target: at least 24 candidates where staged repositories permit; repositories are whole-split to avoid near-duplicate changed-file leakage.
- primary repositories and backups retain their registry role; replacement is logged below.

## Candidate decisions

- click-3865: selected from pallets/click (pallets__click); split=dev; source=d036881798e34289a49b18a5c550c7cf687e5a7a; fix=70689853e39c30e36eb0d83d586cc914a74db9d3; status=admitted
- click-3818: selected from pallets/click (pallets__click); split=dev; source=b47c0529e99129d4785fecc2cb39a8ec8b4aa5f8; fix=00f257bb8e714064bea16425007543bbc0800445; status=admitted
- click-3805: selected from pallets/click (pallets__click); split=dev; source=3cbcf9b11546f4cf10b36d3e2e531733ba6fe001; fix=4295457ddc7b5ca9a733d59ca40d9651b02b9b1d; status=admitted
- click-3764: selected from pallets/click (pallets__click); split=dev; source=150d1071d69c5cdad7de78590013ffe56cf9e3bb; fix=fc5c7f45da0a4443f60ba2d322fe4bf829977739; status=admitted
- click-3678: selected from pallets/click (pallets__click); split=dev; source=8c1a0a7abbc1c36f70d1f65f3604acc46c5ce6ab; fix=b67832c2167e5b0ff6764a8c04a0a9087e697b5a; status=admitted
- click-3533: selected from pallets/click (pallets__click); split=dev; source=cd9bdd96a9dcc8e4ecabd45b5c244dbc70034484; fix=4df304c658666f34a5ca4335ab0da15832f02f9e; status=admitted
- tqdm-1830: selected from tqdm/tqdm (tqdm__tqdm); split=holdout; source=8d6ff8de5a9066de77d0a9df3e80a022a3dcf146; fix=9cf5a12b1f955468a17f0ba3c59092b23e4258ac; status=admitted
- tqdm-1473: selected from tqdm/tqdm (tqdm__tqdm); split=holdout; source=4a7f422734a765d3df89ad7dbfec3ef1baf53b30; fix=181fc2e4c8700c332ef032aad59a7e9a824cd5e0; status=rejected
- tqdm-1781: selected from tqdm/tqdm (tqdm__tqdm); split=holdout; source=6ab24dcc5df910044f1f6e0685f95dbf9cd424f3; fix=93370ff891582e458c40196ea78a1a9d720fbb45; status=admitted
- attrs-1593: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=6851ab593cd25f3c14393e9355d57d22bec2a074; fix=97f8d175656bc03c373a1c9038048a4d312c307c; status=rejected
- attrs-1513: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=ab7f8b2f4c0f747d5b1575247ce35e5adaad182e; fix=af9c510912ce604a94896cc35c27368d5baf6ae6; status=rejected
- attrs-1461: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=19175d91df292e9d0722ecb6575043f1d124a123; fix=ce358ed0e6c4bf38a46efa51cc03a02164e2795d; status=rejected
- attrs-1446: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=cbaef3f8f5ec3d6049b42c8c27f542c1571bb4c8; fix=000c563473400aa086f6486a9c38ace0e77ea219; status=rejected
- attrs-1428: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=94caa57142c057ce52504cdf239ae0ed3168f9b5; fix=937b1e232803cc4ec9b9375ef525fc57c24ec498; status=rejected
- attrs-1381: selected from python-attrs/attrs (python-attrs__attrs); split=holdout; source=160f5d8b97b3af606dca4c1fbb00ca9248366f75; fix=2a76643e36aa7e07d13f9438857a7cff48b4a1d6; status=rejected
- tomlkit-550: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=21a4942ed31e773061c9fc047d55b1bb3c637ee3; fix=495a42ecc9119eaaeb895def0fd025a71cd1cf60; status=rejected
- tomlkit-551: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=67d3e86502706df2a9ed67114ab67e25bcdcbbb7; fix=8cd44f58b499da3c80a29bc877a512665a15e0bb; status=rejected
- tomlkit-549: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=e23a25438c6cc9b8cc28b6dcf76dc52f9c7a33e3; fix=67d3e86502706df2a9ed67114ab67e25bcdcbbb7; status=rejected
- tomlkit-545: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=34e51e2d6d09af86970f266a4217cea839fdc347; fix=e23a25438c6cc9b8cc28b6dcf76dc52f9c7a33e3; status=rejected
- tomlkit-533: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=d3c76f0bbe90af4b12a3b83bd8e59bc9061dfe85; fix=43668ddebc3f082bf385d328aceed18d26976897; status=rejected
- tomlkit-530: selected from python-poetry/tomlkit (python-poetry__tomlkit); split=holdout; source=f40ae46323992b1cda523424bdfb30de899eb4f6; fix=d3c76f0bbe90af4b12a3b83bd8e59bc9061dfe85; status=rejected
- jinja-1665: selected from pallets/jinja (pallets__jinja); split=dev; source=fbc3a696c729d177340cc089531de7e2e5b6f065; fix=c8fdce1e0333f1122b244b03a48535fdd7b03d91; status=admitted
- jinja-2061: selected from pallets/jinja (pallets__jinja); split=dev; source=767b23617628419ae3709ccfb02f9602ae9fe51f; fix=b4b28ec01c60b8753ab53fe60b10d7dbaa55842b; status=rejected
- jinja-1852: selected from pallets/jinja (pallets__jinja); split=dev; source=48b0687e05a5466a91cd5812d604fa37ad0943b4; fix=767b23617628419ae3709ccfb02f9602ae9fe51f; status=admitted
- jinja-2029: selected from pallets/jinja (pallets__jinja); split=dev; source=ba8847a466d0f3ad622502f86e819737a4b9fdc7; fix=1dc04bccf9384cced4262d7ca7157638b0ebd970; status=admitted
- jinja-1984: selected from pallets/jinja (pallets__jinja); split=dev; source=20be10e566a505cc47bdec5fa6ad56d5fbdfb4ae; fix=3ef3ba885bc7a465b022abfd525d6bb4a1c8dd3c; status=admitted
- jinja-1979: selected from pallets/jinja (pallets__jinja); split=dev; source=e82013c39970c336ed33906b3c38464f1fadbd30; fix=8a8e2bc4d7605a5f717357e4043cde7a0aeacfd7; status=rejected
- httpx-3131: selected from encode/httpx (encode__httpx); split=holdout; source=f3eb3c90fdd19d2e4c5239e19a3588d072ff53fb; fix=0006ed0547f8f8a3cbe2edf758e996c3c73b5e7d; status=rejected
- httpx-3116: selected from encode/httpx (encode__httpx); split=holdout; source=df5345140e09ac6c2de0d9589bcd6f3e31c6aa3f; fix=6d852d319acd5d97caf14037dff15ede04b37542; status=rejected
- zod-6587: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=0c483c58849fdb6445aea4f54b1bac6b57ab3d22; fix=9446b5cc14c5bf137790f1f66abf602044871223; status=admitted
- zod-6582: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=dd9c36fa2ddcee79f71d19f9635586c7b65ead86; fix=b12aa523e7e2617c4296cccf9b24d6558ed23e95; status=rejected
- zod-6580: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=574d480fb443d3fd396efbcb8230f3dfee4a2cd2; fix=dd9c36fa2ddcee79f71d19f9635586c7b65ead86; status=admitted
- zod-6572: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=22bed613281143efa3815fe26ab666c6c56586af; fix=36f17960d1defca5d0896d9424f4e1059fbbf081; status=admitted
- zod-6570: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=277613a61a11f299d9897ddd88490002a995f746; fix=dcbcf0529ca1e5424541d5d4b58e0a7b79507f51; status=admitted
- zod-6553: selected from colinhacks/zod (colinhacks__zod); split=holdout; source=5489a532e65ee3f5ab0959ff8a5da346ced96f2a; fix=7a00236683c79000dbab0d92f6faf0b7fba39f59; status=admitted
- immer-1289: selected from immerjs/immer (immerjs__immer); split=holdout; source=d2c158f5bac7081a760bbaf501ea5c360b7856e1; fix=907395ad21aef22ed2c71d11f4fb4172683ab62a; status=rejected
- immer-1283: selected from immerjs/immer (immerjs__immer); split=holdout; source=a3be9df762c1dbe9959a011ddbab0ce838cbc468; fix=d2c158f5bac7081a760bbaf501ea5c360b7856e1; status=admitted
- immer-1249: selected from immerjs/immer (immerjs__immer); split=holdout; source=7cab3c27d52972273a29b62f22c519493a45e0f4; fix=a3be9df762c1dbe9959a011ddbab0ce838cbc468; status=rejected
- immer-1251: selected from immerjs/immer (immerjs__immer); split=holdout; source=8bc4b2d49a3a01eeb8f19f200bac183e9a7deaa6; fix=e38ad71f256844bf2dc28c1120c33c930c881bb6; status=admitted
- immer-1255: selected from immerjs/immer (immerjs__immer); split=holdout; source=cfec5e51660aabd5f9026d3de1a0793630ef20c0; fix=a73672ab76b5d9fd94f278a23c6c1931a03147e5; status=admitted
- immer-1271: selected from immerjs/immer (immerjs__immer); split=holdout; source=60ca295e1185db80322ef55ec3fb8475cbc960c7; fix=4d3d6ff88caa85734a802a91cdb3dbe004d88b17; status=rejected
- zustand-3555: selected from pmndrs/zustand (pmndrs__zustand); split=holdout; source=f44cecc72a8ec39fbd270fc29e2058806932bf2a; fix=3febf8c6d4f6670f886cc6b628b01a128d2888bd; status=rejected
- zustand-3511: selected from pmndrs/zustand (pmndrs__zustand); split=holdout; source=8476d2ca288d787c1ffdd53615f44c85e98f87be; fix=ad77bd3bb6f7bbd12fea8b458ed5c0673df0793a; status=rejected
- zustand-3469: selected from pmndrs/zustand (pmndrs__zustand); split=holdout; source=4b96f4e3a53abdbb1419cacadddc9b1bd786dab3; fix=4e9bcf0c82938cfe2463495a845806cd5ec3e59b; status=rejected
- execa-1259: selected from sindresorhus/execa (sindresorhus__execa); split=holdout; source=499fe800361e6b383b0085f635a69fd27e6cf447; fix=e7717338a35aa53196ba3cad1498a1a50cd3905c; status=rejected
- execa-1232: selected from sindresorhus/execa (sindresorhus__execa); split=holdout; source=f3a2e8481a1e9138de3895827895c834078b9456; fix=3ed0544b697fea99a367869a80a69589c026c4a8; status=rejected
- execa-1199: selected from sindresorhus/execa (sindresorhus__execa); split=holdout; source=2f1012fc3e7be6bcf520e3f3f5459cc8aa2769d2; fix=1ac5b91eaaed89cc8b6a3d123e1af42ed65f9c33; status=rejected
- pluggy-731: selected from pytest-dev/pluggy (pytest-dev__pluggy); split=dev; source=87e45202858dbb725c2ea7d6472a11c1a2624518; fix=080b7d31074f773540c9e66f9d4c00a47159a35f; status=admitted
- pluggy-632: selected from pytest-dev/pluggy (pytest-dev__pluggy); split=dev; source=59e66fdb231bf47ce5e0b8ed75b788820b135c34; fix=5d7bd2cc083571466f44f9683136b7d8f62b88bf; status=rejected
- pluggy-646: selected from pytest-dev/pluggy (pytest-dev__pluggy); split=dev; source=6e1d0f13a259776bbf137f90bd7ab8b4474f68e7; fix=20d8143f127a4d7526dbbea441857b4b80ec8bdd; status=admitted
- requests-7502: selected from psf/requests (psf__requests); split=holdout; source=661970d171d9c3e12e4c789c4768db647d8c4da0; fix=6f205ff422bccd5e4c4fc0b64c5f3e7df5181db6; status=rejected
- requests-7433: selected from psf/requests (psf__requests); split=holdout; source=0b401c76b6e80a4eecf3c690085b2553f6e261ca; fix=6404f345e562d962abe6700a1c357ec1e7e18232; status=rejected
- requests-7395: selected from psf/requests (psf__requests); split=holdout; source=6ec76b4a36fba4a32fb72f5f9ba04e632635e477; fix=27e0981962d355b9532256f4dcb3d42f64b04d9c; status=rejected
- ky-881: selected from sindresorhus/ky (sindresorhus__ky); split=holdout; source=0bda554d448c1b57c17a5c18114432c02465d467; fix=99644d0169138eb0c42718f06862061288f05a96; status=rejected
- ky-880: selected from sindresorhus/ky (sindresorhus__ky); split=holdout; source=294fe63be57d73bda18194b7e23ab7225c054643; fix=0bda554d448c1b57c17a5c18114432c02465d467; status=rejected
- ky-867: selected from sindresorhus/ky (sindresorhus__ky); split=holdout; source=6edddd986f2f6a9c7d91e851d9b9a48df439d328; fix=06375efbacfc1bdc96f7a4de7560684b765e1274; status=rejected

Admission freeze

Admission status is now frozen from the operator-staged offline runs. No candidate
was replaced after observing task outcomes. Rejected candidates remain listed as
frozen candidates with their exact rejection evidence; they are never eligible
for scoring. The dev split has 15 frozen candidates and 12 admitted tasks. The
holdout split has 41 frozen candidates and 10 admitted tasks because the staged
Python, Node, browser, and submodule caches did not make the remaining candidates
admissible offline. This is an infrastructure shortfall, not an outcome-based
selection rule.

No post-outcome candidate swap was performed. Test and cache deviations are recorded in each admission.json.
