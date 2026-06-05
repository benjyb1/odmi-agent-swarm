const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
p.author = "Benjamin Bream";
p.title = "ODMI Agent Swarm - Progress";

// palette
const INK="0F2A43", INK2="163A57", TEAL="0E7C86", TEALL="5EC8C8",
      MINT="13A38A", AMBER="B45309", AMBERBG="FFF4E5",
      SLATE="1E293B", MUTE="64748B", LIGHT="F1F5F9", BORDER="CBD5E1",
      ICE="CADCFC", WHITE="FFFFFF";
const HEAD="Georgia", BODY="Calibri";
const W=13.33, H=7.5;
const shadow = () => ({ type:"outer", color:"0F2A43", blur:7, offset:2, angle:135, opacity:0.12 });

function card(s,x,y,w,h,fill,line){
  s.addShape(p.shapes.ROUNDED_RECTANGLE,{x,y,w,h,rectRadius:0.07,
    fill:{color:fill}, line: line?{color:line,width:1}:{type:"none"}, shadow:shadow()});
}

// ---------- SLIDE 1 : TITLE ----------
let s = p.addSlide(); s.background={color:INK};
s.addText("MSC ADVANCED COMPUTING   ·   KING'S COLLEGE LONDON   ·   2026",
  {x:0.75,y:0.85,w:12,h:0.4,fontFace:BODY,fontSize:13,color:TEALL,charSpacing:2,bold:true});
s.addText("Automating the EU Open Data\nMaturity Index with an LLM agent swarm",
  {x:0.75,y:1.55,w:11,h:2.3,fontFace:HEAD,fontSize:40,bold:true,color:WHITE,lineSpacingMultiple:1.05});
s.addText("An agent swarm that answers ODMI questions across 36 countries, with every answer traced to a source, and able to challenge each country's self-report.",
  {x:0.75,y:4.25,w:10.6,h:1.1,fontFace:BODY,fontSize:18,color:ICE,lineSpacingMultiple:1.1});
s.addText("Benjamin Bream   ·   Progress review, June 2026",
  {x:0.75,y:6.85,w:9,h:0.4,fontFace:BODY,fontSize:13,color:"7FA8C9"});
// motif: 6x6 grid = 36 countries
{ const gx=11.0, gy=4.95, sz=0.2, gap=0.075;
  let n=0;
  for(let r=0;r<6;r++)for(let c=0;c<6;c++){
    const op = 0.25 + 0.6*((r+c)/10);
    s.addShape(p.shapes.RECTANGLE,{x:gx+c*(sz+gap),y:gy+r*(sz+gap),w:sz,h:sz,
      fill:{color:TEALL,transparency:Math.round((1-op)*100)},line:{type:"none"}});
    n++;
  }
  s.addText("36 countries",{x:gx-0.2,y:gy+6*(sz+gap)+0.05,w:2.3,h:0.3,fontFace:BODY,fontSize:11,color:"7FA8C9",align:"center"});
}

// ---------- SLIDE 2 : PROBLEM + AIM ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("The problem, and the aim",{x:0.7,y:0.45,w:12,h:0.7,fontFace:HEAD,fontSize:32,bold:true,color:INK});
// big stat block
card(s,0.7,1.45,3.7,3.15,TEAL,null);
s.addText("5,148",{x:0.7,y:1.7,w:3.7,h:1.2,fontFace:HEAD,fontSize:54,bold:true,color:WHITE,align:"center"});
s.addText("(question × country) pairs\nassessed every cycle",{x:0.85,y:2.95,w:3.4,h:0.7,fontFace:BODY,fontSize:14,color:WHITE,align:"center",lineSpacingMultiple:1.05});
s.addText("36 countries  ·  143 questions  ·  20+ languages",{x:0.85,y:3.75,w:3.4,h:0.6,fontFace:BODY,fontSize:12,color:ICE,align:"center"});
// aim box
card(s,0.7,4.85,3.7,2.05,INK,null);
s.addText("THE AIM",{x:0.95,y:5.05,w:3.2,h:0.35,fontFace:BODY,fontSize:12,bold:true,color:TEALL,charSpacing:2});
s.addText("Answer them automatically, trace every answer to a source, and flag where the self-report does not hold up.",
  {x:0.95,y:5.45,w:3.25,h:1.3,fontFace:BODY,fontSize:15,color:WHITE,lineSpacingMultiple:1.1});
// problem cards 2x2
s.addText("Why it is hard today",{x:4.85,y:1.45,w:8,h:0.45,fontFace:BODY,fontSize:18,bold:true,color:TEAL});
const probs=[
  ["Self-reported","Countries grade their own homework, so figures can be inflated."],
  ["Manual and slow","Expert review, one country at a time, every cycle."],
  ["Subjective","Assessors read the same question in different ways."],
  ["Multilingual","20+ languages; no single reviewer can cover them all."]];
{ const x0=4.85,y0=2.0,cw=3.9,ch=2.25,gx=0.3,gy=0.3;
  probs.forEach((pr,i)=>{
    const cx=x0+(i%2)*(cw+gx), cy=y0+Math.floor(i/2)*(ch+gy);
    card(s,cx,cy,cw,ch,LIGHT,BORDER);
    s.addShape(p.shapes.OVAL,{x:cx+0.3,y:cy+0.32,w:0.5,h:0.5,fill:{color:TEAL},line:{type:"none"}});
    s.addText(String(i+1),{x:cx+0.3,y:cy+0.32,w:0.5,h:0.5,fontFace:BODY,fontSize:16,bold:true,color:WHITE,align:"center",valign:"middle"});
    s.addText(pr[0],{x:cx+1.0,y:cy+0.32,w:cw-1.2,h:0.5,fontFace:BODY,fontSize:17,bold:true,color:INK,valign:"middle"});
    s.addText(pr[1],{x:cx+0.32,y:cy+1.0,w:cw-0.6,h:1.1,fontFace:BODY,fontSize:13.5,color:SLATE,lineSpacingMultiple:1.05});
  });
}

// ---------- SLIDE 3 : METHODOLOGY ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("How the swarm works",{x:0.7,y:0.4,w:12,h:0.7,fontFace:HEAD,fontSize:32,bold:true,color:INK});
{ const iw=11.5, ih=iw*1096/2209; const ix=(W-iw)/2, iy=1.15;
  s.addImage({path:"/tmp/diag.png",x:ix,y:iy,w:iw,h:ih});
  s.addText("Each agent is a fixed pipeline, not an autonomous loop. The LLM is used only where it earns its place; some answers need none.",
    {x:0.7,y:iy+ih+0.08,w:12,h:0.45,fontFace:BODY,fontSize:13,italic:true,color:MUTE,align:"center"});
}

// ---------- SLIDE 4 : EVALUATION ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("How we evaluate, and what we are still deciding",{x:0.7,y:0.45,w:12.2,h:0.7,fontFace:HEAD,fontSize:30,bold:true,color:INK});
// left: what we measure
s.addText("What we measure",{x:0.7,y:1.4,w:5.4,h:0.45,fontFace:BODY,fontSize:18,bold:true,color:TEAL});
s.addText([
  {text:"Compare each answer to ODMI's published 2025 answers, the ground truth.",options:{bullet:true,breakLine:true}},
  {text:"Score every pair: match / differ / abstain.",options:{bullet:true,breakLine:true}},
  {text:"Stratify by ODMI dimension (Policy, Portal, Quality, Impact) and by country.",options:{bullet:true}}],
  {x:0.7,y:1.9,w:5.4,h:2.0,fontFace:BODY,fontSize:14.5,color:SLATE,lineSpacingMultiple:1.12,paraSpaceAfter:8});
card(s,0.7,4.05,5.4,1.7,AMBERBG,AMBER);
s.addText("The ground truth may be wrong",{x:0.95,y:4.2,w:5,h:0.4,fontFace:BODY,fontSize:15,bold:true,color:AMBER});
s.addText("A disagreement is not automatically our error. Each one gets a human glance.",
  {x:0.95,y:4.6,w:5,h:1.0,fontFace:BODY,fontSize:13.5,color:SLATE,lineSpacingMultiple:1.05});
s.addText("We stepped back from France after a high false-positive rate.",
  {x:0.7,y:5.95,w:5.4,h:0.6,fontFace:BODY,fontSize:13,italic:true,color:MUTE});
// right: open question - held out test
card(s,6.45,1.35,6.15,5.55,LIGHT,BORDER);
s.addText("Open question: the held-out test",{x:6.75,y:1.55,w:5.6,h:0.45,fontFace:BODY,fontSize:18,bold:true,color:INK});
s.addText("If we tune on the answers we score on, we leak. We need a held-out test, not just validation.",
  {x:6.75,y:2.0,w:5.55,h:0.7,fontFace:BODY,fontSize:13,italic:true,color:MUTE,lineSpacingMultiple:1.05});
const opts=[
  ["Hold out by country","Malta (English isolates reasoning) + NL (tests the multilingual path), unseen during development."],
  ["Hold out by question","One country, e.g. France: develop on half the questions, test on the other half."],
  ["Similar-country leave-one-out","Pair countries by profile; develop on one, test the held-out twin."]];
{ const x0=6.75,y0=2.75,cw=5.55,ch=1.18,gy=0.16;
  opts.forEach((o,i)=>{
    const cy=y0+i*(ch+gy);
    card(s,x0,cy,cw,ch,WHITE,BORDER);
    s.addText(o[0],{x:x0+0.25,y:cy+0.14,w:cw-0.5,h:0.4,fontFace:BODY,fontSize:14.5,bold:true,color:TEAL});
    s.addText(o[1],{x:x0+0.25,y:cy+0.52,w:cw-0.5,h:0.6,fontFace:BODY,fontSize:12.5,color:SLATE,lineSpacingMultiple:1.0});
  });
}

// ---------- SLIDE 5 : RESULTS ----------
s = p.addSlide(); s.background={color:WHITE};
s.addText("Early results",{x:0.7,y:0.4,w:8,h:0.7,fontFace:HEAD,fontSize:32,bold:true,color:INK});
s.addText("222 finalised pairs across 6 countries. Numbers still growing since moving off France.",
  {x:0.7,y:1.05,w:12,h:0.4,fontFace:BODY,fontSize:13,italic:true,color:MUTE});
// two stat callouts
card(s,0.7,1.55,5.9,1.65,WHITE,BORDER);
s.addText([{text:"88%",options:{fontSize:46,bold:true,color:TEAL,fontFace:HEAD}}],{x:0.95,y:1.62,w:2.3,h:1.5,valign:"middle"});
s.addText("agreement with ODMI when the swarm commits an answer (136 of 154 decided pairs).",
  {x:3.25,y:1.62,w:3.2,h:1.5,fontFace:BODY,fontSize:14,color:SLATE,valign:"middle",lineSpacingMultiple:1.05});
card(s,6.7,1.55,5.9,1.65,WHITE,BORDER);
s.addText([{text:"27%",options:{fontSize:46,bold:true,color:AMBER,fontFace:HEAD}}],{x:6.95,y:1.62,w:2.3,h:1.5,valign:"middle"});
s.addText("of pairs it abstains on rather than guess (an honest \"inconclusive\").",
  {x:9.25,y:1.62,w:3.1,h:1.5,fontFace:BODY,fontSize:14,color:SLATE,valign:"middle",lineSpacingMultiple:1.05});
// bar chart commit-agreement by country
s.addText("Agreement when committing, by country",{x:0.7,y:3.45,w:5.9,h:0.4,fontFace:BODY,fontSize:14,bold:true,color:INK});
s.addChart(p.charts.BAR,[{name:"agreement",labels:["France (n=94)","Malta (n=48)"],values:[94,75]}],{
  x:0.55,y:3.9,w:5.9,h:3.0,barDir:"col",chartColors:[TEAL],
  chartArea:{fill:{color:"FFFFFF"}},valAxisMinVal:0,valAxisMaxVal:100,
  catAxisLabelColor:MUTE,catAxisLabelFontSize:12,valAxisLabelColor:MUTE,
  valGridLine:{color:"E2E8F0",size:0.5},catGridLine:{style:"none"},
  showValue:true,dataLabelPosition:"outEnd",dataLabelColor:SLATE,dataLabelFontBold:true,
  dataLabelFormatCode:'0"%"',showLegend:false,showTitle:false});
s.addText("Other countries n<10; not shown.",{x:0.7,y:6.9,w:5.9,h:0.3,fontFace:BODY,fontSize:10.5,italic:true,color:MUTE});
// self-report box
card(s,6.7,3.45,5.9,3.45,INK,null);
s.addText("The self-report ceiling",{x:6.95,y:3.65,w:5.4,h:0.45,fontFace:BODY,fontSize:18,bold:true,color:TEALL});
s.addText([
  {text:"France self-reported ",options:{}},
  {text:">90%",options:{bold:true,color:WHITE}},
  {text:" on licence coverage and metadata conformance.",options:{breakLine:true}},
  {text:"Independent recompute from the portal reads ",options:{breakLine:false}},
  {text:"~38%",options:{bold:true,color:"FCA5A5"}},
  {text:" and ",options:{}},
  {text:"~32%",options:{bold:true,color:"FCA5A5"}},
  {text:".",options:{breakLine:true}}],
  {x:6.95,y:4.15,w:5.4,h:1.8,fontFace:BODY,fontSize:15,color:ICE,lineSpacingMultiple:1.15});
s.addText("So the system can be more accurate than the ground truth, not just track it.",
  {x:6.95,y:5.9,w:5.4,h:0.8,fontFace:BODY,fontSize:14,italic:true,color:WHITE,lineSpacingMultiple:1.05});

// ---------- SLIDE 6 : EXPERIMENTS + NEXT ----------
s = p.addSlide(); s.background={color:INK};
s.addText("What we are testing next",{x:0.7,y:0.55,w:12,h:0.8,fontFace:HEAD,fontSize:32,bold:true,color:WHITE});
const exp=[
  ["Verifier strategies","How hard the Verifier is set against the evidence to disprove a claim before it stands."],
  ["Retry chaining","Feed a failed attempt's context into the retry, or retry from scratch each time?"],
  ["Cost vs quality","Search-depth knobs: what does one more unit of accuracy actually cost?"]];
{ const x0=0.7,y0=1.7,cw=3.9,ch=2.85,gx=0.31;
  exp.forEach((e,i)=>{
    const cx=x0+i*(cw+gx);
    card(s,cx,y0,cw,ch,INK2,TEAL);
    s.addShape(p.shapes.OVAL,{x:cx+0.35,y:y0+0.4,w:0.55,h:0.55,fill:{color:TEAL},line:{type:"none"}});
    s.addText(String(i+1),{x:cx+0.35,y:y0+0.4,w:0.55,h:0.55,fontFace:BODY,fontSize:18,bold:true,color:WHITE,align:"center",valign:"middle"});
    s.addText(e[0],{x:cx+0.35,y:y0+1.15,w:cw-0.7,h:0.5,fontFace:BODY,fontSize:17,bold:true,color:TEALL});
    s.addText(e[1],{x:cx+0.35,y:y0+1.7,w:cw-0.7,h:1.0,fontFace:BODY,fontSize:13.5,color:ICE,lineSpacingMultiple:1.1});
  });
}
s.addText("NEXT",{x:0.7,y:5.0,w:3,h:0.35,fontFace:BODY,fontSize:13,bold:true,color:TEALL,charSpacing:2});
s.addText([
  {text:"Scale to more countries (Malta dispatch queued).",options:{bullet:true,breakLine:true}},
  {text:"Lock the held-out evaluation set, then report accuracy on unseen countries.",options:{bullet:true}}],
  {x:0.7,y:5.4,w:11.8,h:1.1,fontFace:BODY,fontSize:15,color:ICE,lineSpacingMultiple:1.15,paraSpaceAfter:6});
s.addText("Receipts for every answer; honest about every disagreement.",
  {x:0.7,y:6.75,w:12,h:0.5,fontFace:HEAD,fontSize:16,italic:true,color:MINT});

const out="/Users/benjyb/Desktop/Msc Project/.claude/worktrees/jolly-allen-c23112/docs/ODMI_Progress_5min.pptx";
p.writeFile({fileName:out}).then(f=>console.log("WROTE",f));
