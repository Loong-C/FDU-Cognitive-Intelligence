"""从冻结逐条输出复算组内阶段报告，不向API发送请求。"""
from pathlib import Path
import sys, json, csv, hashlib, html, re, shutil, zipfile
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark import read_sources, grouped_scores, LABELS
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics import renderSVG
from pypdf import PdfReader

OUT=ROOT.parent/'笔记'/'认知智能PJ-组内阶段分享-20261029'
OUT.mkdir(exist_ok=True)
(OUT/'附件').mkdir(exist_ok=True)
pdfmetrics.registerFont(TTFont('CJK','C:/Windows/Fonts/simhei.ttf'))
BLUE=colors.HexColor('#2364aa'); INK=colors.HexColor('#17324d')
NAMES={'baseline':'Baseline','general':'通用草稿','v3':'v3原轮','v3r1':'v3复测1','v3r2':'v3复测2'}
MECH={'DENIAL':'否认与事实','LOOKALIKE':'相似人物','UNIQUE':'唯一性','PRESUP':'时间与预设','TEMPSCOPE':'任期与时间范围','SETCLOSE':'名单封闭范围','AMBIGREF':'指代归属'}
SHORT={'SUPPORTS':'S','REFUTES':'R','NOT ENOUGH INFO':'N'}
styles={
 'title':ParagraphStyle('title',fontName='CJK',fontSize=21,leading=29,spaceAfter=16,textColor=INK),
 'h':ParagraphStyle('h',fontName='CJK',fontSize=14,leading=20,spaceBefore=10,spaceAfter=9,textColor=INK),
 'p':ParagraphStyle('p',fontName='CJK',fontSize=10,leading=16,spaceAfter=8,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='CJK',fontSize=9.2,leading=14,spaceAfter=5,wordWrap='CJK'),
 'cell':ParagraphStyle('cell',fontName='CJK',fontSize=9.0,leading=13,wordWrap='CJK')}
story=[]; web=[]; md=[]; chartnum=0

def text(s,kind='p'):
 story.append(Paragraph(html.escape(s).replace('\n','<br/>'),styles[kind]))
 tag={'title':'h1','h':'h2','p':'p','small':'p'}[kind]
 web.append(f'<{tag} class="{kind}">{html.escape(s).replace(chr(10),"<br>")}</{tag}>')
 md.append(('# ' if kind=='title' else '## ' if kind=='h' else '')+s+'\n')

def table(headers,rows,widths=None):
 cells=[[Paragraph(html.escape(str(c)),styles['cell']) for c in row] for row in [headers,*rows]]
 t=Table(cells,colWidths=widths or [503/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eff7')),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#ccd8e3')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
 story.extend([t,Spacer(1,9)])
 web.append('<div class="table"><table><thead><tr>'+''.join('<th>'+html.escape(str(c))+'</th>' for c in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table></div>')
 md.extend(['| '+' | '.join(map(str,headers))+' |','| '+' | '.join(['---']*len(headers))+' |',*['| '+' | '.join(map(str,r))+' |' for r in rows],''])

def page(title):
 if story:story.append(PageBreak());web.append('</section><section>')
 else:web.append('<section>')
 text(title,'title')

def draw_label(d,x,y,s,size=9,color=INK,anchor='start'):
 d.add(String(x,y,s,fontName='CJK',fontSize=size,fillColor=color,textAnchor=anchor))

def chart(d,name):
 global chartnum
 chartnum+=1
 story.extend([d,Spacer(1,10)])
 svg=renderSVG.drawToString(d)
 svg=svg[svg.index('<svg'):]
 svg=re.sub(r'font-family:[^;"}]+', 'font-family:Microsoft YaHei, SimHei, sans-serif',svg)
 svg=svg.replace('font-family="CJK"','font-family="Microsoft YaHei, SimHei, sans-serif"')
 (OUT/'附件'/f'{name}.svg').write_text(svg,encoding='utf-8')
 web.append('<figure>'+svg+'</figure>')
 md.append(f'![{name}](附件/{name}.svg)\n')

def bars(title,series,maximum=100,height=175):
 d=Drawing(503,height);draw_label(d,0,height-15,title,11)
 left=82;right=465;bottom=25;top=height-38
 for tick in [0,25,50,75,100]:
  if tick<=maximum:
   x=left+(right-left)*tick/maximum;d.add(Line(x,bottom,x,top,strokeColor=colors.HexColor('#dce5ed'),strokeWidth=.5));draw_label(d,x,bottom-13,str(tick),7,anchor='middle')
 band=(top-bottom)/max(1,len(series))
 for i,(name,value,color) in enumerate(series):
  y=top-(i+1)*band+band*.18
  draw_label(d,left-7,y+band*.18,name,9,anchor='end')
  d.add(Rect(left,y,(right-left)*value/maximum,band*.62,fillColor=color,strokeColor=None))
  draw_label(d,min(487,left+(right-left)*value/maximum+5),y+band*.17,f'{value:.2f}%',8)
 return d

def matrices(items):
 height=200 if len(items)<=3 else 390
 d=Drawing(503,height)
 for index,(name,m) in enumerate(items):
  col=index%3;row=index//3;x=col*168+27;y=height-row*190-42;cell=36
  draw_label(d,x+cell*1.5,y+19,name,9,anchor='middle')
  for j,a in enumerate('SRN'):draw_label(d,x+j*cell+18,y+4,a,8,anchor='middle')
  for i,g in enumerate(LABELS):
   draw_label(d,x-8,y-i*cell-23,'SRN'[i],8,anchor='end')
   total=sum(m['confusion_matrix'][g].values())
   for j,p in enumerate(LABELS):
    n=m['confusion_matrix'][g][p];ratio=n/total
    color=colors.Color(.94-.70*ratio,.97-.52*ratio,1-.30*ratio)
    d.add(Rect(x+j*cell,y-(i+1)*cell,cell,cell,fillColor=color,strokeColor=colors.white,strokeWidth=1))
    draw_label(d,x+j*cell+18,y-i*cell-22,str(n),9,colors.white if ratio>.65 else INK,'middle')
  draw_label(d,x+54,y-125,'预测标签 →',7,anchor='middle')
 draw_label(d,0,10,'行 = 真实标签，列 = 预测标签；颜色深浅按每行比例，格内为样本数。',8)
 return d

def read(path):
 if not path.exists():return {}
 raw=path.read_text(encoding='utf-8')
 if not raw.endswith('\n'):raw=raw[:raw.rfind('\n')+1]
 rows=[json.loads(x) for x in raw.splitlines() if x.strip()]
 assert len(rows)==len({r['id'] for r in rows})
 return {r['id']:r for r in rows}

def experiment(folder,key):
 p=ROOT/'results'/folder
 records=read(p/(key+'.jsonl'))
 retry=read(p/(key+'-network-retry.jsonl')) if folder.startswith('general') else read(p/'network-retry/retry.jsonl')
 for i,r in retry.items():
  if r['status']=='ok':records[i]=r
 return records

def fmt(x):return f'{x:.2%}' if x is not None else '未完成'

def dumpcsv(name,headers,rows):
 with (OUT/'附件'/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(headers);w.writerows(rows)


datasets,baseprompt,audit=read_sources()
folders={'baseline':'full-4096-20261027','general':'general-full-20261029','v3':'challenge-prompt-v3-full-20261028','v3r1':'challenge-prompt-v3-repeat1-20261028','v3r2':'challenge-prompt-v3-repeat2-20261028'}
records={k:{'challenge':experiment(v,'challenge')} for k,v in folders.items()}
for k in ['baseline','general']:records[k]['basic']=experiment(folders[k],'basic')
metrics={k:{d:grouped_scores(datasets[d],r) for d,r in v.items()} for k,v in records.items()}
complete={d:len(records['general'][d])==len(datasets[d]) for d in datasets}
captured=datetime.now().astimezone().isoformat(timespec='seconds')
sourcehashes={}
for folder in folders.values():
 for p in (ROOT/'results'/folder).rglob('*.jsonl'):sourcehashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
gc=metrics['general']['challenge'];bc=metrics['baseline']['challenge'];vc=metrics['v3']['challenge']
snapshot={'captured_at':captured,'general_complete':complete,'metrics':metrics,'source_hashes':sourcehashes,'data_audit':audit}
(OUT/'附件/指标与来源快照.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

page('事实判断PJ阶段进展')
text('Baseline、通用提示词与v3的组内分享版','h')
text('这份报告用于同步目前做到了什么、卡在哪里，以及下一步如何验证。结果来自已有逐条预测的重新统计；不包含训练或LoRA实验。')
text('统计快照：'+captured+'。S=支持，R=反驳，N=信息不足。','small')
text(f'当前最清楚的结论：A组原始模板在挑战集为{fmt(bc["accuracy"])}；增加一段通用判断原则后为{fmt(gc["accuracy"])}，净多答对{gc["correct"]-bc["correct"]}条；加入机制规则的v3三轮为85.08%～85.54%。总分改善主要来自NEI误判减少，但仍有大量证据不足被误判为反驳。')
rows=[]
for k in NAMES:
 c=metrics[k]['challenge'];b=metrics[k].get('basic')
 bstr=f'{b["correct"]}/900 ({fmt(b["accuracy"])})' if b and (k=='baseline' or complete['basic']) else f'进行中 {len(records[k]["basic"])}/900' if b else '尚未评测'
 rows.append([NAMES[k],f'{c["correct"]}/885',fmt(c['accuracy']),f'{c["macro_f1"]:.4f}',bstr])
table(['版本','挑战集正确数','Accuracy','Macro-F1','基础集'],rows,[80,80,75,72,196])
if complete['basic']:
 b=metrics['baseline']['basic'];g=metrics['general']['basic']
 text(f'需要注意的代价：通用版基础集为{fmt(g["accuracy"])}，相对Baseline的{fmt(b["accuracy"])}净少答对{b["correct"]-g["correct"]}条，变化{(g["accuracy"]-b["accuracy"])*100:+.2f}个百分点。挑战集收益与基础能力回退应一起报告。')
chart(bars('挑战集准确率',[(NAMES[k],metrics[k]['challenge']['accuracy']*100,BLUE if k!='general' else colors.HexColor('#15988c')) for k in NAMES]),'准确率对比')
text('v3三轮是同一885条样本的重复请求，不是三个独立测试集。全量结果包含网络失败处理；主跑分数及恢复数量另列。未完成的基础集不报最终准确率。','small')

page('我们具体比较了什么')
table(['维度','Baseline','通用草稿','v3'],[
 ['任务说明','A组原始模板','完整保留原始模板','完整保留原始任务定义'],
 ['新增指导','无额外指导','一段统一的逻辑与证据原则','三项反驳检查及机制规则'],
 ['专项规则','无','无','否认、人物、时间、名单及范围'],
 ['示例数量','0','0','0'],
 ['推理调用','每样本一次','每样本一次','每样本一次；复测独立计分'],
 ['输入字段','evidence和claim','evidence和claim','evidence和claim'],
 ],[65,128,140,170])
text('统一配置：服务模型名qwen38-27b；temperature=0；enable_thinking=false；max_tokens=4096；并发4。原始标签、证据和陈述未改。group、mechanism、gold等不输入模型，只用于离线统计。')
text('通用版新增内容的中文含义','h')
text('依据证据陈述的事实及其必然逻辑结果判断整个陈述；区分已建立事实与额外假设；尊重限定词的含义和范围；缺少支持不构成反驳；支持与反驳均未建立时选择NEI；每条输入使用同一标准。')
text('v3进一步写明：反驳前找出事实依据、检查推导假设、尝试证据与陈述能否同时成立；区分他人否认与事实否定、其他人获奖与主体没获奖、某次发生与首次/唯一发生，并保留完整名单的有效排除力。')
text('数据与评测边界','h')
text('挑战集885条：S 342、R 118、N 425，共143个group。基础集900条：S 246、R 305、N 349，共105个group。两份集合分别计分，不能合并成一个总分。')
text('数据复核状态：挑战集885条的human_review_status为adjudicated；基础900条该字段为pending。本轮沿用A组标签计分，未重新完成基础集人工裁决。','small')
text('所有三类Recall、Precision、F1均给出。Macro-F1是三类F1的平均值。失败不从总分分母删除；本文最终网络恢复分数只替换请求级网络失败，绝不按答案正确与否挑选重跑。')
text('A方参考部署是Q8_0，当前服务量化尚未独立核实，不能把与A方66.67%参考分的差异归因于提示词或某一种量化。现有挑战集已经参与错误分析，结果属于开发评估；zero-shot仅表示没有示例，并不表示提示词未优化。','small')

page('混淆矩阵看错误流向')
text('每个矩阵均覆盖挑战集885条。观察N行R列：这是“信息不足被判成反驳”的数量；观察R行N列：这是过度谨慎可能带来的反向损失。')
chart(matrices([(NAMES[k],metrics[k]['challenge']) for k in NAMES]),'挑战集混淆矩阵')
for k in ['baseline','general','v3']:
 m=metrics[k]['challenge']['confusion_matrix'];text(f'{NAMES[k]}：N→R {m["NOT ENOUGH INFO"]["REFUTES"]}/425；R→N {m["REFUTES"]["NOT ENOUGH INFO"]}/118；S→N {m["SUPPORTS"]["NOT ENOUGH INFO"]}/342。','small')
text('v3的反驳召回仍然较高，但预测为反驳时的精确率只有约一半。这意味着“能抓到真反驳”和“判成反驳就可信”是两件不同的事，不能只看REFUTES Recall。')

page('各类别指标逐项列出')
rows=[]
for k in NAMES:
 for label in LABELS:
  m=metrics[k]['challenge']['per_class'][label]
  rows.append([NAMES[k],SHORT[label],m['support'],fmt(m['precision']),fmt(m['recall']),f'{m["f1"]:.4f}'])
table(['版本','标签','样本数','Precision','Recall','F1'],rows,[85,40,65,100,100,113])
text('Precision：预测为该类的样本中有多少是真的。Recall：真实该类样本中找回多少。F1综合考虑两者；标签N即NOT ENOUGH INFO。','small')
chart(bars('NEI召回率',[(NAMES[k],metrics[k]['challenge']['per_class']['NOT ENOUGH INFO']['recall']*100,colors.HexColor('#15988c')) for k in NAMES],height=155),'NEI召回率')

page('不同困难机制的结果')
for metric,title in [('accuracy','准确率'),('nei','NEI召回率')]:
 text(title,'h');rows=[]
 for mechanism in sorted(MECH):
  item=metrics['baseline']['challenge']['by_mechanism'][mechanism]
  row=[MECH[mechanism],str(item['count'])]
  for k in NAMES:
   m=metrics[k]['challenge']['by_mechanism'][mechanism]
   row.append(fmt(m['accuracy'] if metric=='accuracy' else m['per_class']['NOT ENOUGH INFO']['recall']))
  rows.append(row)
 table(['机制','条数',*NAMES.values()],rows,[96,35,73,79,73,73,74])
text('机制标签仅用于离线拆分，未作为输入。不同机制的NEI样本占比不同，因此不能把机制准确率直接当成NEI召回率。完整机制级三类Precision/Recall/F1另附CSV。','small')
text('通用版相对Baseline在七个机制上的净增正确数依次为：指代+3、否认+15、相似人物+12、时间预设+9、名单范围+1、任期时间+1、唯一性+7。各机制总分均未下降，但个别样本仍有退步，不能把净提升解释为没有损失。','small')
text('三轮始终错90条中：相似人物24、时间与预设22、指代归属22、唯一性13、名单范围5、任期与时间3、否认与事实1。这些是v3三轮的交集错误，并非通用版的错误分布。')

page('改善了哪些 又损失了哪些')
base=records['baseline']['challenge']
pairrows=[]
for k in ['general','v3','v3r1','v3r2']:
 fixed=sum(base[r['id']]['prediction']!=r['label'] and records[k]['challenge'][r['id']]['prediction']==r['label'] for r in datasets['challenge'])
 lost=sum(base[r['id']]['prediction']==r['label'] and records[k]['challenge'][r['id']]['prediction']!=r['label'] for r in datasets['challenge'])
 agree=sum(base[r['id']]['prediction']==records[k]['challenge'][r['id']]['prediction'] for r in datasets['challenge'])
 pairrows.append([NAMES[k],fixed,lost,f'{fixed-lost:+d}',f'{agree}/885'])
table(['相对Baseline','纠正错题','原对变错','净增正确','预测一致'],pairrows,[120,90,90,95,108])
text('v3稳定性与90%目标','h')
rep=json.loads((ROOT/'results/v3-repeat-comparison-20261028/summary.json').read_text(encoding='utf-8'))
table(['比较','预测一致率','纠正','退步','净变化'],[[name.replace('original_v3','原v3').replace('repeat1','复测1').replace('repeat2','复测2').replace('__',' vs '),fmt(v['agreement_rate']),v['corrected'],v['regressed'],f'{v["net"]:+d}'] for name,v in rep['paired'].items()],[170,100,75,75,83])
text('三轮有81条样本预测发生变化，90条三轮都错，其中82条金标准为NEI。三轮总分范围只有0.46个百分点，但逐条预测一致率约94%，总分稳定不等于每道题稳定。')
text('三轮多数票757/885（85.54%），没有超过最好单轮。利用真实标签事后挑选三轮中正确答案可覆盖795/885（89.83%）；它不可部署，只是三轮现有答案的正确覆盖数。至少90%需要797/885，最好单轮还需净多答对40条。')
text('网络恢复与主跑口径','h')
table(['轮次','主跑正确','网络失败','恢复后正确'],[['Baseline','605/885','0','605/885'],['通用版',f'{gc["correct"]}/885','0',f'{gc["correct"]}/885'],['v3原轮','756/885','1','756/885'],['v3复测1','744/885','13','753/885'],['v3复测2','755/885','2','757/885']],[120,125,125,133])

examples=[
 ('e_8cd325ba12347b9a','已经改善的例子：他人否认不等于事实为假',None,'助理把“Brandi Carlile秘密收养了一只叫Whiskey的救助犬”的报道斥为毫无根据。','Brandi Carlile秘密收养了这只犬。','证据建立的是助理作出否认，没有独立建立事件未发生。这类提醒在通用版里已经能改善部分样本。'),
 ('e_de5850002a981ff4','仍然困难：同姓被补成同一家族',None,'John Faithfull是其家族中唯一获得该格莱美奖的人。','Marianne Faithfull获得了该奖。','“唯一”只在该家族内生效。文本没有证明Marianne属于该家族；同姓不能提供这个前提。'),
 ('e_7325d6294ac00a1a','仍然困难：指代正确 结论却越界',None,'Melania Trump与兄弟Miha Knavs于1992年在卢布尔雅那就读。1995年，他获得一项全国建筑奖。','Melania Trump在1995年获得该奖。','即使he正确指向兄弟，也只证明兄弟获奖；尚未排除Melania也获奖。'),
 ('e_e4d322f586379996','仍然困难：某年获奖被当成首次获奖','Tim Burton won the Academy Award for Best Animated Feature in 2023.','Tim Burton于2023年获奖。','Tim Burton在2023年以前获过该奖。','2023年一次获奖与更早另一次获奖可以共存。不能自行补出“首次”或“只有一次”。'),
 ('e_3af48c4e223c3693','仍然困难：首段任期被当成全部任期',None,'Shuntaro Furukawa首次担任任天堂总裁的任期为2015至2023年。','他在2025年担任任天堂总裁。','first served限定首次任期，没有排除后来再次任职。模型多次在复述时漏掉first。'),
 ('e_107863750565aa1a','仍然困难：子集名单被扩大为全集','Jim Harbaugh has two children born in the 1990s: Carter and Bryson.','Jim Harbaugh有两名出生于1990年代的孩子：Carter和Bryson。','Lindsey是他的孩子之一。','证据只封闭出生于1990年代的子集；Lindsey可能出生于其他年代。'),
 ('e_c802018beea08dd8','需要单独讨论：范围缺口与金标准','Hegseth\'s two co-hosts are Maria Bartiromo and Katie Pavlich.','证据给出两名共同主持人，但长证据未明确节目名称。','Brian Kilmeade是他在Fox & Friends Weekend的共同主持人之一。','金标准为REFUTES；v3认为节目范围没有确立而选NEI。它体现限定范围与标注口径的边界争议。保留金标准照常计错，不为提高分数改标签；需要组内和A组一起核对。')]
rowmap={r['id']:r for r in datasets['challenge']}
for pageindex in range(3):
 page(['困难样本 从否认到人物归属','困难样本 从时间到集合范围','标注边界与下一步'][pageindex])
 subset=examples[pageindex*3:pageindex*3+3] if pageindex<2 else examples[6:]
 for i,title,excerpt,zh,czh,why in subset:
  row=rowmap[i];evidence=excerpt or row['evidence']
  text(title,'h')
  text('证据原文'+('（节选）' if evidence!=row['evidence'] else '')+'：'+evidence,'small')
  text('陈述原文：'+row['claim'],'small')
  text('中文理解：'+zh+' 陈述：'+czh,'small')
  verdicts='；'.join(NAMES[k]+'='+SHORT[records[k]['challenge'][i]['prediction']] for k in ['baseline','general','v3'])
  text('金标准='+SHORT[row['label']]+'；'+verdicts,'small')
  text(why,'p');text('样本ID：'+i,'small')
 if pageindex==2:
  text('目前真正卡住的地方','h')
  text('模型往往能找到原文、解析人名或日期，但在推出否定结论时仍偷偷加入“只有一个”“同一家族”“只发生一次”等前提；增加一般性提醒改善了一部分，尚未消除这些固定误判。')
  text('下一步建议','h')
  text('通用版基础集已发现净少答对7条，应先复核退步样本，并补做v3基础集。保留A组原模板作固定baseline、v3作已有强对照；每次只调整一个通用推理环节，并记录纠正与退步。若继续做90%目标，需要实际达到797条正确，不能由85%左右的重复分数外推。' if complete['basic'] else '先完成通用版基础集检查，再决定是否修改提示词。保留A组原模板作固定baseline、v3作已有强对照；每次只调整一个通用推理环节，并记录纠正与退步。')
  text('当前885条挑战集已经用于调优，新增独立盲测数据更适合检验迁移；按group隔离同一场景变体。LoRA尚未启动，是否需要训练应由剩余错例和新数据表现决定。')

page('基础能力与可复核附件')
if complete['basic']:
 bm=metrics['baseline']['basic'];gm=metrics['general']['basic']
 text(f'通用版基础集{gm["correct"]}/900（{fmt(gm["accuracy"])}），相对Baseline净变化{gm["correct"]-bm["correct"]:+d}条，准确率变化{(gm["accuracy"]-bm["accuracy"])*100:+.2f}个百分点。该结果用于检查通用指导是否牺牲基础判断能力。')
 table(['版本','正确数','Accuracy','Macro-F1'],[[NAMES[k],f'{metrics[k]["basic"]["correct"]}/900',fmt(metrics[k]['basic']['accuracy']),f'{metrics[k]["basic"]["macro_f1"]:.4f}'] for k in ['baseline','general']])
 chart(matrices([(NAMES[k],metrics[k]['basic']) for k in ['baseline','general']]),'基础集混淆矩阵')
 table(['版本','标签','Precision','Recall','F1'],[[NAMES[k],SHORT[l],fmt(metrics[k]['basic']['per_class'][l]['precision']),fmt(metrics[k]['basic']['per_class'][l]['recall']),f'{metrics[k]["basic"]["per_class"][l]["f1"]:.4f}'] for k in ['baseline','general'] for l in LABELS])
 page('基础能力分项与附件')
 text('基础集各机制准确率','h')
 table(['机制','样本数','Baseline','通用草稿'],[[m,metrics['baseline']['basic']['by_mechanism'][m]['count'],fmt(metrics['baseline']['basic']['by_mechanism'][m]['accuracy']),fmt(metrics['general']['basic']['by_mechanism'][m]['accuracy'])] for m in metrics['baseline']['basic']['by_mechanism']])
else:
 text(f'生成快照时通用版基础集完成{len(records["general"]["basic"])}/900，仍在运行；本报告不报部分样本的最终准确率。完成后应更新此页。')
text('v3基础900条尚未评测，因此还不能确认v3在基础任务上是否回退。机制级Macro-F1固定对三类取平均；某机制没有某一类时，该类F1按原评分器记0，不宜与全体三类齐全的Macro-F1直接横比。','small')
text('附件提供什么','h')
text('逐条预测对照.csv：1785条样本，一行一题，含完整证据、陈述、金标准、Baseline/通用/v3三轮预测；未评测字段留空。另有总体指标、机制级全指标、所选错例全文与理由，以及三种提示词原文。')
text('来源：A组原数据包benchmark_1011(1).zip；results/full-4096-20261027；results/general-full-20261029；v3原轮及两次复测目录。完整源文件SHA256见指标与来源快照.json。分享包不包含密钥、请求头或.env。','small')

# 全量可复核数据
detail=[]
for key,rows in datasets.items():
 for r in rows:
  i=r['id'];detail.append([key,i,r['group'],r['mechanism'],r.get('variant',''),r['label'],r['claim'],r['evidence'],*[records[k].get(key,{}).get(i,{}).get('prediction','') for k in NAMES],*[records[k].get(key,{}).get(i,{}).get('status','not_evaluated') for k in NAMES]])
dumpcsv('逐条预测对照.csv',['dataset','id','group','mechanism','variant','gold','claim','evidence',*NAMES.keys(),*[k+'_status' for k in NAMES]],detail)
metricrows=[]
for k,ds in metrics.items():
 for dataset,m in ds.items():
  if k=='general' and not complete[dataset]:continue
  for mechanism,x in [('ALL',m),*m['by_mechanism'].items()]:
   for l,p in x['per_class'].items():metricrows.append([k,dataset,mechanism,x['count'],x['correct'],x['accuracy'],x['macro_f1'],l,p['support'],p['precision'],p['recall'],p['f1']])
dumpcsv('总体与机制全指标.csv',['version','dataset','mechanism','count','correct','accuracy','macro_f1','label','support','precision','recall','f1'],metricrows)
matrixrows=[]
for k,ds in metrics.items():
 for dataset,m in ds.items():
  if k=='general' and not complete[dataset]:continue
  for gold,line in m['confusion_matrix'].items():
   for pred,count in line.items():matrixrows.append([k,dataset,gold,pred,count])
dumpcsv('混淆矩阵原始计数.csv',['version','dataset','gold','prediction','count'],matrixrows)
selected=[{'sample':rowmap[i],'predictions':{k:records[k]['challenge'][i] for k in NAMES}} for i,*_ in examples]
(OUT/'附件/困难样本全文与模型理由.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'附件/A组原始Baseline提示词.txt').write_text(baseprompt+'\n',encoding='utf-8')
for name,source in [('通用草稿提示词.txt','prompt-general-draft-20261028/prompt-general.txt'),('v3提示词.txt','prompt-v3-draft-20261028/prompt-v3.txt')]:shutil.copyfile(ROOT/'results'/source,OUT/'附件'/name)
css='''body{margin:0;background:#eef3f8;color:#17324d;font-family:"Microsoft YaHei",sans-serif;line-height:1.8}main{max-width:1060px;margin:30px auto}section{background:white;padding:35px 45px;margin:20px 0;border-radius:10px}h1{font-size:28px}h2{font-size:20px;margin-top:28px}.small{font-size:13px;color:#456}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border:1px solid #ccd8e3;padding:9px;text-align:left}th{background:#e7eff7}.table{overflow:auto}svg{width:100%;height:auto}figure{margin:20px 0}@media(max-width:650px){section{padding:20px}main{margin:0}}@media print{body{background:white}section{break-before:page;margin:0;padding:0}section:first-child{break-before:auto}}'''
(OUT/'认知智能PJ阶段报告.html').write_text('<!doctype html><html lang="zh"><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>认知智能PJ阶段报告</title><style>'+css+'</style><main>'+''.join(web)+'</section></main></html>',encoding='utf-8')
(OUT/'认知智能PJ阶段报告.md').write_text('\n'.join(md),encoding='utf-8')
def footer(c,doc):
 c.saveState();c.setFont('CJK',8);c.setFillColor(INK);c.drawString(46,24,'事实判断PJ · 组内阶段分享 · 2026-10-29');c.drawRightString(549,24,str(doc.page));c.restoreState()
pdf=OUT/'认知智能PJ阶段报告.pdf'
SimpleDocTemplate(str(pdf),pagesize=(595.28,841.89),leftMargin=46,rightMargin=46,topMargin=36,bottomMargin=39,title='认知智能PJ阶段进展').build(story,onFirstPage=footer,onLaterPages=footer)
reader=PdfReader(pdf)
assert len(detail)==1785
for k,ds in records.items():
 for dataset,r in ds.items():
  assert all(r[x['id']]['gold']==x['label'] for x in datasets[dataset] if x['id'] in r)
  if len(r)==len(datasets[dataset]):assert metrics[k][dataset]['correct']==sum(r[x['id']]['prediction']==x['label'] for x in datasets[dataset])
verification={'passed':True,'captured_at':captured,'pdf_pages':len(reader.pages),'per_item_rows':1785,'all_ids_unique_and_gold_checked':True,'correct_counts_recomputed':True,'general_complete':complete,'charts':chartnum}
(OUT/'附件/报告验收.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'out':str(OUT),**verification},ensure_ascii=False))
