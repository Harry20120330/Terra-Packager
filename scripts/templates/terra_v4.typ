// Terra Library Publication Template (terra-reading-v4) — Typst 0.15.1
#let payload = json(sys.inputs.at("data", default: "data.json"))

#let c-ink = rgb("#141414")
#let c-accent = rgb("#22313D")
#let c-muted = rgb("#545454")
#let c-rule = rgb("#B4B9BD")

#let p-lang = payload.primary_lang
#let s-lang = payload.secondary_lang
#let is-bilingual = payload.bilingual
#let p-font = payload.primary_cjk_font
#let s-font = payload.secondary_cjk_font

#set document(
  title: payload.doc_title,
  author: "泰拉文库 / Terra Library",
)

#let diamond-ornament() = {
  box(baseline: -2.2pt, stack(
    dir: ltr,
    spacing: 6pt,
    line(length: 16mm, stroke: 0.35pt + c-accent),
    move(dy: -1.6pt, rotate(45deg, rect(width: 3.1pt, height: 3.1pt, fill: c-accent, stroke: none))),
    line(length: 16mm, stroke: 0.35pt + c-accent),
  ))
}

#let txt-p(body, size: 10.5pt, fill: c-ink, weight: "regular", style: "normal", tracking: 0pt) = {
  let fonts = if p-lang == "en" {
    ("EB Garamond", p-font)
  } else {
    ((name: "EB Garamond", covers: "latin-in-cjk"), p-font)
  }
  text(
    font: fonts,
    lang: payload.primary_typst_lang,
    region: payload.primary_typst_region,
    size: size,
    fill: fill,
    weight: weight,
    style: style,
    tracking: tracking,
    body,
  )
}

#let txt-s(body, size: 9.4pt, fill: c-muted, weight: "regular", style: "normal", tracking: 0pt) = {
  let fonts = if s-lang == "en" {
    ("EB Garamond", s-font)
  } else {
    ((name: "EB Garamond", covers: "latin-in-cjk"), s-font)
  }
  text(
    font: fonts,
    lang: payload.secondary_typst_lang,
    region: payload.secondary_typst_region,
    size: size,
    fill: fill,
    weight: weight,
    style: style,
    tracking: tracking,
    body,
  )
}

// ==================== 1. COVER PAGE ====================
#page(
  paper: "a4",
  margin: 0mm,
  header: none,
  footer: none,
  numbering: none,
)[
  #place(
    top + left,
    dx: 15mm,
    dy: 15mm,
    rect(width: 180mm, height: 267mm, stroke: 0.75pt + c-ink),
  )
  #place(
    top + left,
    dx: 17.6mm,
    dy: 17.6mm,
    rect(width: 174.8mm, height: 261.8mm, stroke: 0.3pt + c-ink),
  )

  #align(center)[
    #v(64mm)
    #text(
      font: ("Cormorant Garamond", "EB Garamond", p-font),
      weight: "light",
      size: 11pt,
      tracking: 3.6pt,
      fill: c-muted,
      "ARKNIGHTS",
    )
    #v(2.5mm)
    #txt-p(payload.ui.cover_sub, size: 8pt, fill: c-muted, tracking: 1.5pt)

    #v(42mm)
    #pad(x: 26mm)[
      #set par(leading: 0.45em)
      #txt-p(payload.volume_title_primary, size: 31pt, fill: c-accent)
      #if is-bilingual and payload.volume_title_secondary != "" and payload.volume_title_secondary != payload.volume_title_primary [
        #v(3.5mm)
        #txt-s(
          payload.volume_title_secondary,
          size: 15pt,
          fill: c-muted,
          style: if s-lang == "en" { "italic" } else { "normal" },
        )
      ]
    ]

    #v(7mm)
    #diamond-ornament()
    #v(5mm)
    #txt-p(payload.edition_badge, size: 8.5pt, fill: c-muted, tracking: 0.8pt)
  ]

  #place(
    bottom + center,
    dy: -27.5mm,
    align(center)[
      #txt-p(payload.ui.cover_rights, size: 7.8pt, fill: c-muted, tracking: 0.3pt)
      #v(2.2mm)
      #text(
        font: ("Cormorant Garamond", "EB Garamond", p-font),
        size: 7.8pt,
        fill: c-muted,
        tracking: 1.8pt,
        "TERRA LIBRARY",
      )
      #h(3pt)
      #txt-p("· 泰拉文库", size: 7.8pt, fill: c-muted, tracking: 1.2pt)
    ],
  )
]

// ==================== 2. TABLE OF CONTENTS ====================
#page(
  paper: "a4",
  margin: (inside: 27mm, outside: 20mm, top: 24mm, bottom: 22mm),
  header: none,
  footer: none,
)[
  #v(8mm)
  #align(center)[
    #txt-p(payload.ui.toc_heading, size: 15pt, fill: c-accent, tracking: 1.8pt)
    #v(3mm)
    #diamond-ornament()
  ]
  #v(9mm)

  #context {
    let headings = query(heading)
    for (idx, sec) in payload.sections.enumerate() {
      let target-page = if idx < headings.len() {
        headings.at(idx).location().page()
      } else {
        0
      }
      let loc = if idx < headings.len() { headings.at(idx).location() } else { here() }

      let level = sec.heading_level
      block(
        width: 100%,
        above: if sec.is_divider and level == 1 { 5pt } else { 0pt },
        below: if sec.is_divider { 8pt } else { 6pt },
        inset: (left: (level - 1) * 4mm),
        breakable: false,
      )[
        #link(loc)[
          #grid(
            columns: (1fr, auto),
            column-gutter: 4mm,
            align: (left + horizon, right + horizon),
            [
              #box(width: 100%)[
                #if sec.tag_primary != "" [
                  #txt-p(sec.tag_primary + " · ", size: 8pt, fill: c-muted)
                ]
                #txt-p(
                  sec.title_primary,
                  size: if sec.is_divider { 11pt } else { 10pt },
                  fill: c-ink,
                  weight: if sec.is_divider { "semibold" } else { "regular" },
                )
                #if is-bilingual and sec.title_secondary != "" and sec.title_secondary != sec.title_primary [
                  #h(3pt)
                  #txt-s("/ " + sec.title_secondary, size: 9.5pt, fill: c-muted, style: if s-lang == "en" { "italic" } else { "normal" })
                ]
              ]
            ],
            [
              #txt-p(str(target-page), size: 10pt, fill: c-muted)
            ],
          )
        ]
      ]
    }
  }
]

// ==================== 3. STORY BODY ====================
#set page(
  paper: "a4",
  margin: (inside: 27mm, outside: 20mm, top: 25.5mm, bottom: 22.5mm),
  header-ascent: 8.5mm,
  header: context {
    let pno = here().page()
    let has-heading = query(heading).any(h => h.location().page() == pno)
    if has-heading {
      none
    } else {
      let prev-h = query(selector(heading).before(here()))
      let cur-sec-title = if prev-h.len() > 0 { prev-h.last().body } else { payload.volume_title_primary }
      block(width: 100%, below: 0pt)[
        #if calc.even(pno) [
          #grid(
            columns: (auto, 1fr),
            align: (left + bottom, right + bottom),
            txt-p(str(pno), size: 8pt, fill: c-muted),
            txt-p(payload.volume_title_primary, size: 8pt, fill: c-muted, tracking: 0.5pt),
          )
        ] else [
          #grid(
            columns: (1fr, auto),
            align: (left + bottom, right + bottom),
            txt-p(cur-sec-title, size: 8pt, fill: c-muted, tracking: 0.5pt),
            txt-p(str(pno), size: 8pt, fill: c-muted),
          )
        ]
        #v(2mm)
        #line(length: 100%, stroke: 0.35pt + c-muted)
      ]
    }
  },
  footer: none,
)

#set par(justify: false, leading: 0.48em)
#show heading: it => {
  // Invisible bookmark anchor; custom visual header rendered directly below
  block(above: 0pt, below: 0pt, height: 0pt, sticky: true)[]
}

#let source-lines(body) = {
  for (idx, part) in body.split("\n").enumerate() {
    if idx > 0 { linebreak() }
    part
  }
}

#let render-utterance(blk) = {
  let indent-shift = if blk.depth > 1 { (blk.depth - 1) * 4mm } else { 0mm }
  let prose = [
    #if blk.txt_p != "" [
      #txt-p(source-lines(blk.txt_p))
    ]
    #if is-bilingual and blk.txt_s != "" [
      #if blk.txt_p != "" [ #parbreak() #v(-3pt) ]
      #txt-s(source-lines(blk.txt_s))
    ]
  ]

  let content-node = if blk.depth > 0 {
    block(
      width: 100%,
      inset: (left: 3mm, top: 0.5pt, bottom: 0.5pt),
      stroke: (left: 0.4pt + c-rule),
      prose,
    )
  } else {
    block(width: 100%, above: 0pt, below: 0pt, prose)
  }

  block(width: 100%, above: 0pt, below: 11.4pt, inset: (left: indent-shift), content-node)
}

#for (sec_idx, sec) in payload.sections.enumerate() [
  #if sec.is_divider and sec.heading_level == 1 [
    #pagebreak(weak: true)
  ] else if sec_idx > 0 [
    #v(if sec.heading_level == 1 { 14mm } else { 8mm }, weak: true)
  ]
  #block(width: 100%, breakable: false, sticky: true, above: 0pt, below: if sec.is_divider { 5mm } else { 7.5mm })[
    #heading(level: sec.heading_level, outlined: true, bookmarked: true)[#sec.title_primary]
    #align(if sec.is_divider and sec.heading_level > 1 { left } else { center })[
      #let title-size = if sec.is_divider and sec.heading_level == 1 { 25pt } else if sec.heading_level == 1 { 20pt } else if sec.heading_level == 2 { 17pt } else { 14.5pt }
      #txt-p(sec.title_primary, size: title-size, fill: c-accent, tracking: 1pt)
      #if is-bilingual and sec.title_secondary != "" and sec.title_secondary != sec.title_primary [
        #v(2mm)
        #txt-s(
          sec.title_secondary,
          size: 11.5pt,
          fill: c-muted,
          style: if s-lang == "en" { "italic" } else { "normal" },
        )
      ]
      #if sec.heading_level == 1 [
        #v(2.8mm)
        #diamond-ornament()
      ]
      #if sec.tag_primary != "" [
        #v(2.4mm)
        #txt-p(sec.tag_primary, size: 7.5pt, fill: c-muted, tracking: 1.2pt)
      ]
    ]
  ]

  #for blk in sec.blocks [
    #if blk.kind == "utterance" [
      #render-utterance(blk)
    ] else if blk.kind == "choices" [
      #block(width: 100%, above: 9pt, below: 9pt, inset: (left: blk.depth * 4mm))[
        #for opt in blk.options [
          #block(width: 100%, above: 0pt, below: 5.5pt, breakable: false)[
            #grid(
              columns: (6mm, 1fr),
              align: (left + top, left + top),
              txt-p(str(opt.index) + ".", size: 10pt, fill: c-accent),
              [
                #if opt.txt_p != "" [
                  #txt-p(source-lines(opt.txt_p), size: 10.2pt, fill: c-ink)
                ]
                #if is-bilingual and opt.txt_s != "" [
                  #if opt.txt_p != "" [ #linebreak() ]
                  #txt-s(source-lines(opt.txt_s), size: 9.2pt, fill: c-muted)
                ]
              ],
            )
          ]
        ]
      ]
    ] else if blk.kind == "branch_notice" [
      #block(width: 100%, above: 9.5pt, below: 5.5pt, sticky: true, inset: (left: blk.depth * 4mm))[
        #txt-p(blk.label, size: 8.3pt, fill: c-accent, tracking: 1pt)
      ]
    ] else if blk.kind == "shared_notice" [
      #block(width: 100%, above: 9.5pt, below: 6pt, sticky: true)[
        #txt-p(blk.label, size: 8.3pt, fill: c-accent, tracking: 1pt)
      ]
    ]
  ]
]
