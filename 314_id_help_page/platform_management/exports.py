import csv
from io import StringIO,BytesIO
from xml.sax.saxutils import escape
from flask import Response

def export_report(mode,data,rows,totals,categories):
    if mode=='csv':
        stream=StringIO(); writer=csv.writer(stream)
        writer.writerow(['Period starting','New projects','View events','Shortlist events','Content reports'])
        writer.writerows([[r[k] for k in ['date','projects','views','shortlists','reports']] for r in rows])
        return Response(stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=business_report.csv'})
    if mode=='pdf':
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        stream=BytesIO(); styles=getSampleStyleSheet()
        category=next((c['name'] for c in categories if c['id']==data['category']),'All categories')
        story=[Paragraph('Business report',styles['Title']),Paragraph(escape(f"{data['period'].title()} | {data['start']} to {data['end']} | {category}"),styles['Normal']),Spacer(1,16)]
        cells=[['Period starting','Projects','Views','Shortlists','Reports']]+[[str(r[k]) for k in ['date','projects','views','shortlists','reports']] for r in rows]+[['TOTAL']+[str(totals[k]) for k in ['projects','views','shortlists','reports']]]
        table=Table(cells,repeatRows=1,colWidths=[120,70,70,70,70])
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173f3a')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.3,colors.lightgrey),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story += [table,Spacer(1,16),Paragraph('Singapore dates inclusive. Weeks start Monday; partial periods contain only selected dates. Projects include drafts. Shortlists count save events, not current favourites. Category filters use current assignments.',styles['Normal'])]
        SimpleDocTemplate(stream).build(story)
        return Response(stream.getvalue(),mimetype='application/pdf',headers={'Content-Disposition':'attachment; filename=business_report.pdf'})
