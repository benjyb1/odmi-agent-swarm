const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
p.author = "Benjamin Bream";
p.title = "AI researchers that don't make things up";

const INK="0F2A43", INK2="163A57", TEAL="0E7C86", TEALL="5EC8C8",
      MINT="13A38A", AMBER="B45309", AMBERBG="FFF4E5",
      SLATE="1E293B", MUTE="64748B", LIGHT="F1F5F9", BORDER="CBD5E1",
      ICE="CADCFC", WHITE="FFFFFF", RED="FCA5A5";
const HEAD="Georgia", BODY="Calibri";
const W=13.33, H=7.5;
const shadow = () => ({ type:"outer", color:"0F2A43", blur:7, offset:2, angle:135, opacity:0.12 });
function card(s,x,y,w,h,fill,line){
  s.addShape(p.shapes.ROUNDED_RECTANGLE,{x,y,w,h,rectRadius:0.06,
    fill:{color:fill}, line: line?{color:line,width:1}:{type:"none"}, shadow:shadow()});
}
function eyebrow(s,x,y,t,color){
  s.addText(t,{x,y,w:9,h:0.32,fontFace:BODY,fontSize:12.5,bold:true,color,charSpacing:2});
}

// ---------- SLIDE 1 : TITLE ----------
let s = p.addSlide(); s.background={color:INK};
eyebrow(s,0.75,0.85,"MSC ADVANCED COMPUTING   ·   KING'S COLLEGE LONDON   ·   2026",TEALL);
s.addText("AI researchers that\ndo not make things up",
  {x:0.75,y:1.5,w:11,h:2.3,fontFace:HEAD,fontSize:44,bold:true,color:WHITE,lineSpacingMultiple:1.04});
s.addText("Building and stress-testing an agent swarm that answers only what a source supports. The EU Open Data Maturity Index is the testbed.",
  {x:0.75,y:4.35,w:10.8,h:1.1,fontFace:BODY,fontSize:18,color:ICE,lineSpacingMultiple:1.12});
s.addText("Benjamin Bream   ·   Progress review, June 2026",
  {x:0.75,y:6.85,w:9,h:0.4,fontFace:BODY,fontSize:13,color:"7FA8C9"});
{ const gx=11.0, gy=4.95, sz=0.2, gap=0.075;
  for(let r=0;r<6;r++)for(let c=0;c<6;c++){
    const op=0.25+0.6*((r+c)/10);
    s.addShape(p.shapes.RECTANGLE,{x:gx+c*(sz+gap),y:gy+r*(sz+gap),w:sz,h:sz,
      fill:{color:TEALL,transparency:Math.round((1-op)*100)},line:{type:"none"}});
  }
  s.addText("36 countries  ·  5,148 question-country pairs",{x:gx-2.4,y:gy+6*(sz+gap)+0.05,w:4.7,h:0.3,fontFace:BODY,fontSize:11,color:"7FA8C9",align:"center"});
}

// ---------- SLIDE 2 : PROBLEM / RESEARCH QUESTION ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("A confident answer is not a correct one",{x:0.7,y:0.45,w:12.2,h:0.7,fontFace:HEAD,fontSize:32,bold:true,color:INK});
s.addText("Ask a language model a factual question and it returns a fluent answer whether or not the evidence exists. For an assessment like ODMI, much of it self-reported and across 20+ languages, a fabricated \"yes\" is worse than no answer at all.",
  {x:0.7,y:1.3,w:12.0,h:1.0,fontFace:BODY,fontSize:16,color:SLATE,lineSpacingMultiple:1.15});
// left: failure modes
s.addText("The failure modes we fight",{x:0.7,y:2.65,w:6,h:0.4,fontFace:BODY,fontSize:17,bold:true,color:TEAL});
const fails=[
  ["Fabrication","The model fills a gap with plausible text instead of evidence."],
  ["Overconfidence","A wrong answer arrives sounding as certain as a right one."],
  ["No receipts","A bare label cannot be audited, traced, or trusted."]];
{ const x0=0.7,y0=3.15,cw=5.7,ch=1.05,gy=0.16;
  fails.forEach((f,i)=>{
    const cy=y0+i*(ch+gy);
    card(s,x0,cy,cw,ch,LIGHT,BORDER);
    s.addShape(p.shapes.OVAL,{x:x0+0.28,y:cy+0.28,w:0.5,h:0.5,fill:{color:AMBER},line:{type:"none"}});
    s.addText("!",{x:x0+0.28,y:cy+0.28,w:0.5,h:0.5,fontFace:BODY,fontSize:18,bold:true,color:WHITE,align:"center",valign:"middle"});
    s.addText(f[0],{x:x0+0.98,y:cy+0.16,w:cw-1.2,h:0.36,fontFace:BODY,fontSize:15.5,bold:true,color:INK});
    s.addText(f[1],{x:x0+0.98,y:cy+0.5,w:cw-1.2,h:0.5,fontFace:BODY,fontSize:13,color:SLATE,lineSpacingMultiple:1.0});
  });
}
// right: research question box
card(s,6.75,2.95,5.85,3.8,INK,null);
eyebrow(s,7.05,3.2,"THE RESEARCH QUESTION",TEALL);
s.addText("How do you build an agent that asserts only what a source supports, abstains when it cannot, and how do you prove it is not bluffing?",
  {x:7.05,y:3.65,w:5.3,h:2.0,fontFace:HEAD,fontSize:21,color:WHITE,italic:true,lineSpacingMultiple:1.18});
s.addText("ODMI is a hard testbed: 5,148 pairs, self-reported answers to check, 36 countries.",
  {x:7.05,y:5.95,w:5.3,h:0.7,fontFace:BODY,fontSize:13,color:ICE,lineSpacingMultiple:1.05});

// ---------- SLIDE 3 : THE RESEARCHER ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("The Researcher: constrained so it cannot invent",{x:0.7,y:0.4,w:12.4,h:0.7,fontFace:HEAD,fontSize:30,bold:true,color:INK});
{ const iw=11.5, ih=iw*1096/2209; const ix=(W-iw)/2, iy=1.12;
  s.addImage({path:"/tmp/diag.png",x:ix,y:iy,w:iw,h:ih});
  s.addText("Deterministic where possible (zero-LLM catalogue answers)   ·   trusted-domain search with the answer key deny-listed   ·   one reasoning pass over a fixed evidence bundle",
    {x:0.5,y:iy+ih+0.06,w:12.4,h:0.45,fontFace:BODY,fontSize:12.5,italic:true,color:MUTE,align:"center"});
}

// ---------- SLIDE 4 : THE CHECKS ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("How the system checks it did not make it up",{x:0.7,y:0.45,w:12.4,h:0.7,fontFace:HEAD,fontSize:30,bold:true,color:INK});
const checks=[
  ["Grounded in what it read","The cited source must be one the Researcher actually retrieved; the evidence quote is checked against those snippets. It cannot cite what it never saw."],
  ["The source must be real","URL is live (HEAD request), on a trusted domain, and the answer fits the allowed shape for that question."],
  ["An adversary checks the claim","A second agent, the Verifier, is set against the evidence to disprove the answer before it is allowed to stand."],
  ["Abstain over guess","Below a 0.65 confidence floor the system returns an honest \"inconclusive\" instead of committing to an answer."],
  ["Retry before giving up","A weak first pass triggers retries with forced diverging queries, then abstention if it is still unsure."]];
{ const x0=0.7,y0=1.35,cw=11.93,ch=0.96,gy=0.07;
  checks.forEach((c,i)=>{
    const cy=y0+i*(ch+gy);
    card(s,x0,cy,cw,ch,LIGHT,BORDER);
    s.addShape(p.shapes.OVAL,{x:x0+0.3,y:cy+0.23,w:0.5,h:0.5,fill:{color:TEAL},line:{type:"none"}});
    s.addText("✓",{x:x0+0.3,y:cy+0.23,w:0.5,h:0.5,fontFace:BODY,fontSize:20,bold:true,color:WHITE,align:"center",valign:"middle"});
    s.addText(c[0],{x:x0+1.05,y:cy+0.13,w:3.7,h:0.7,fontFace:BODY,fontSize:16,bold:true,color:TEAL,valign:"middle"});
    s.addText(c[1],{x:x0+4.85,y:cy+0.1,w:cw-5.1,h:0.78,fontFace:BODY,fontSize:13,color:SLATE,valign:"middle",lineSpacingMultiple:1.0});
  });
}

// ---------- SLIDE 5 : MEASURING IT HONESTLY ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("Measuring it honestly: the accuracy trap",{x:0.7,y:0.45,w:12.4,h:0.7,fontFace:HEAD,fontSize:30,bold:true,color:INK});
// left: the trap
card(s,0.7,1.4,5.85,5.4,WHITE,BORDER);
eyebrow(s,1.0,1.65,"THE TRAP",AMBER);
s.addText([{text:"98%",options:{fontSize:60,bold:true,color:AMBER,fontFace:HEAD,breakLine:true}},
           {text:"of France's binary answers are \"yes\"",options:{fontSize:14,color:SLATE}}],
  {x:1.0,y:2.0,w:5.25,h:1.5});
s.addText("France's gold is 121 \"yes\" and a single \"no\" (124 binary questions).",
  {x:1.0,y:3.85,w:5.25,h:0.7,fontFace:BODY,fontSize:14.5,color:SLATE,lineSpacingMultiple:1.1});
s.addText("A model that always answers \"yes\" scores 98% and never exposes one false positive. Raw accuracy here measures fluency, not honesty.",
  {x:1.0,y:4.65,w:5.25,h:1.6,fontFace:BODY,fontSize:14.5,bold:true,color:INK,lineSpacingMultiple:1.15});
// right top: the fix
card(s,6.75,1.4,5.85,2.75,INK,null);
eyebrow(s,7.05,1.6,"THE FIX: A BALANCED TESTBED",TEALL);
s.addText([
  {text:"Test on Malta: English is official, so a miss is not a translation artefact. A frozen 60-pair set, 30 \"no\" / 30 \"yes\".",options:{breakLine:true}},
  {text:"",options:{breakLine:true,fontSize:5}},
  {text:"Score with metrics that catch fabrication: false-positive rate, true-negative recall, Youden's J, not raw accuracy.",options:{}}],
  {x:7.05,y:2.0,w:5.3,h:2.0,fontFace:BODY,fontSize:14,color:ICE,lineSpacingMultiple:1.12});
// right bottom: experiments
card(s,6.75,4.35,5.85,2.45,LIGHT,BORDER);
eyebrow(s,7.05,4.55,"EXPERIMENTS RUNNING TO FIND THE BEST CONFIG",TEAL);
s.addText([
  {text:"Verifier strategies",options:{bold:true,color:INK,breakLine:true}},
  {text:"how hard to push the Verifier to disprove a claim.",options:{color:SLATE,breakLine:true}},
  {text:"Retry chaining",options:{bold:true,color:INK,breakLine:true}},
  {text:"recover more answers without committing more false positives.",options:{color:SLATE,breakLine:true}},
  {text:"Cost vs quality",options:{bold:true,color:INK,breakLine:true}},
  {text:"how much accuracy a deeper search actually buys.",options:{color:SLATE}}],
  {x:7.05,y:5.0,w:5.3,h:1.7,fontFace:BODY,fontSize:12.5,lineSpacingMultiple:1.05,paraSpaceAfter:3});

// ---------- SLIDE 6 : WHAT THE HONEST TEST SHOWS ----------
s = p.addSlide(); s.background={color:INK};
s.addText("What the balanced test shows",{x:0.7,y:0.5,w:12,h:0.8,fontFace:HEAD,fontSize:32,bold:true,color:WHITE});
s.addText("Malta, 60-pair base-rate-balanced baseline.",{x:0.7,y:1.25,w:12,h:0.4,fontFace:BODY,fontSize:13,italic:true,color:TEALL});
// two stat cards
card(s,0.7,1.75,3.85,2.2,INK2,TEAL);
s.addText([{text:"0.87",options:{fontSize:44,bold:true,color:TEALL,fontFace:HEAD,breakLine:true}},
           {text:"true-negative recall",options:{fontSize:14,bold:true,color:WHITE,breakLine:true}},
           {text:"only 3 false positives in 23 committed \"no\" answers",options:{fontSize:12.5,color:ICE}}],
  {x:0.95,y:1.95,w:3.4,h:1.8,lineSpacingMultiple:1.05});
card(s,4.74,1.75,3.85,2.2,INK2,TEAL);
s.addText([{text:"17 / 60",options:{fontSize:44,bold:true,color:TEALL,fontFace:HEAD,breakLine:true}},
           {text:"abstained, did not guess",options:{fontSize:14,bold:true,color:WHITE,breakLine:true}},
           {text:"an honest \"inconclusive\" over a forced answer",options:{fontSize:12.5,color:ICE}}],
  {x:4.99,y:1.95,w:3.4,h:1.8,lineSpacingMultiple:1.05});
card(s,8.78,1.75,3.85,2.2,INK2,TEAL);
s.addText([{text:"recall,",options:{fontSize:30,bold:true,color:TEALL,fontFace:HEAD}},
           {text:" not precision",options:{fontSize:22,bold:true,color:WHITE,fontFace:HEAD,breakLine:true}},
           {text:"failures are \"could not find it\", not \"made it up\"",options:{fontSize:12.5,color:ICE}}],
  {x:9.03,y:2.15,w:3.4,h:1.6,lineSpacingMultiple:1.05});
// upside callout
card(s,0.7,4.2,11.93,1.5,"12324A",TEAL);
eyebrow(s,1.0,4.4,"THE UPSIDE",MINT);
s.addText([
  {text:"Where it finds independent evidence it can beat the self-report. France claimed ",options:{}},
  {text:">90%",options:{bold:true,color:WHITE}},
  {text:" on licence coverage and metadata conformance; the recompute reads ",options:{}},
  {text:"~38%",options:{bold:true,color:RED}},
  {text:" and ",options:{}},
  {text:"~32%",options:{bold:true,color:RED}},
  {text:".",options:{}}],
  {x:1.0,y:4.78,w:11.3,h:0.8,fontFace:BODY,fontSize:15,color:ICE,lineSpacingMultiple:1.1});
// next + tagline
s.addText([
  {text:"Next:  ",options:{bold:true,color:TEALL}},
  {text:"lock the balanced held-out set, finish the Verifier and chaining experiments, then scale across countries.",options:{color:ICE}}],
  {x:0.7,y:5.95,w:11.9,h:0.6,fontFace:BODY,fontSize:14.5,lineSpacingMultiple:1.1});
s.addText("It would rather say \"I do not know\" than make something up.",
  {x:0.7,y:6.65,w:12,h:0.5,fontFace:HEAD,fontSize:17,italic:true,color:MINT});

const out="/Users/benjyb/Desktop/Msc Project/.claude/worktrees/jolly-allen-c23112/docs/ODMI_Progress_5min.pptx";
p.writeFile({fileName:out}).then(f=>console.log("WROTE",f));
