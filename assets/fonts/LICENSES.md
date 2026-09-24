# Font licenses (assets/fonts)

The font *binaries* are not committed (git-ignored). `shortkit doctor --fetch-fonts`
(`shortkit.fonts.fetch_all`) downloads them from the canonical URLs pinned in `manifest.yaml`
and refuses any file whose sha256 differs. Every acquirable candidate is licensed under the
**SIL Open Font License 1.1** (full text below). When a font file is redistributed (for example
inside an exported edit project), this file / the copyright notice must travel with it, and the
Reserved Font Names below must not be used for modified versions.

| manifest name | file | copyright notice (from the upstream OFL.txt / LICENSE) | reserved font names | license text URL |
|---|---|---|---|---|
| Pretendard Black / ExtraBold / Bold | Pretendard-{Black,ExtraBold,Bold}.otf | Copyright (c) 2021, Kil Hyung-jin (https://github.com/orioncactus/pretendard); Copyright 2014-2021 Adobe (http://www.adobe.com/); Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter); Copyright 2021 The M+ FONTS Project Authors (https://github.com/coz-m/MPLUS_FONTS) | 'Pretendard', 'Source', 'Inter', 'M PLUS 1' | https://raw.githubusercontent.com/orioncactus/pretendard/main/LICENSE |
| Black Han Sans | BlackHanSans-Regular.ttf | Copyright 2015 The Black Han Sans Project Authors (https://github.com/zesstype/Black-Han-Sans) | — | https://raw.githubusercontent.com/google/fonts/main/ofl/blackhansans/OFL.txt |
| Do Hyeon | DoHyeon-Regular.ttf | Copyright 2018 The Do Hyeon Project Authors | — | https://raw.githubusercontent.com/google/fonts/main/ofl/dohyeon/OFL.txt |
| Jua | Jua-Regular.ttf | Copyright 2018 The Jua Project Authors | — | https://raw.githubusercontent.com/google/fonts/main/ofl/jua/OFL.txt |
| Gothic A1 Black / ExtraBold | GothicA1-{Black,ExtraBold}.ttf | (C) Copyright HanYang I&C Co.,Ltd. All rights reserved. | — | https://raw.githubusercontent.com/google/fonts/main/ofl/gothica1/OFL.txt |
| NanumGothic ExtraBold | NanumGothic-ExtraBold.ttf | Copyright (c) 2010, NHN Corporation (http://www.nhncorp.com) | Nanum, Naver Nanum, NanumGothic, Naver NanumGothic, NanumMyeongjo, Naver NanumMyeongjo, NanumBrush, Naver NanumBrush, NanumPen, Naver NanumPen | https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/OFL.txt |
| Gugi | Gugi-Regular.ttf | Copyright (c) 2017 by TAE System & Typefaces Co.. All rights reserved. | — | https://raw.githubusercontent.com/google/fonts/main/ofl/gugi/OFL.txt |
| Sunflower Bold | Sunflower-Bold.ttf | Copyright 2008 The Sunflower Project Authors | — | https://raw.githubusercontent.com/google/fonts/main/ofl/sunflower/OFL.txt |

The copyright lines above were read from the upstream license files on 2026-09-24.

## System fonts (not shipped; found through fontconfig)

`Noto Sans CJK KR *` (Debian/Ubuntu `fonts-noto-cjk`, `fonts-noto-cjk-extra`; SIL OFL 1.1) and
`Nanum*` (`fonts-nanum`, `fonts-nanum-extra`; SIL OFL 1.1). Their license files are installed by
the OS package.

## Not acquired

Fonts listed in `manifest.yaml` with `status: not_acquired` (Gmarket Sans, 여기어때 잘난체,
Tmon몬소리, 배민 한나체 Pro, S-Core Dream, Cafe24 Ssurround) were **not** downloaded and have no
pinned file; each has its own distribution terms that must be checked at the official
distributor before use. No URL or hash is recorded for them on purpose.

## SIL Open Font License 1.1 (full text)

```
-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```
