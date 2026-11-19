import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import date
import ticket_sorter as core

BASE=Path(__file__).resolve().parent
st.set_page_config(page_title='Hostel Care | Ticket Sorter',page_icon='🏠',layout='wide')
st.markdown('''<style>
.stApp{background:#f4f7fb}.block-container{padding-top:1.8rem;max-width:1250px}
.hero{background:linear-gradient(120deg,#132e4f,#245b83);padding:28px;border-radius:20px;color:white;margin-bottom:20px}
.hero h1{color:white;margin:0}.hero p{color:#dce9f6;margin-bottom:0}
.metric{background:white;border:1px solid #e4eaf2;border-radius:16px;padding:18px}
.metric small{color:#6b7b8e}.metric h2{margin:4px 0;color:#173957}
</style>''',unsafe_allow_html=True)
st.sidebar.markdown('## 🏠 Hostel Care')
page=st.sidebar.radio('Navigation',['Dashboard','Submit Complaint','Ticket Queue','About'])
st.markdown('<div class="hero"><h1>Hostel Maintenance</h1><p>Report issues. Prioritize safely. Keep your hostel running.</p></div>',unsafe_allow_html=True)

@st.cache_data
def load_data():
    complaints=pd.read_csv(BASE/'data/complaints.csv')
    open_tickets=pd.read_csv(BASE/'data/open_tickets.csv')
    return complaints,open_tickets
complaints,open_tickets=load_data()
if 'submitted' not in st.session_state: st.session_state.submitted=[]

if page=='Dashboard':
    total=len(complaints)+len(st.session_state.submitted)
    urgent=sum(str(x.get('urgent','')).lower() in ('true','yes','1') for x in st.session_state.submitted)
    open_count=len(open_tickets)+sum(x.get('status')!='resolved' for x in st.session_state.submitted)
    cols=st.columns(4)
    for c,label,val in zip(cols,['Sample complaints','Urgent new','Open tickets','Resolved'],[len(complaints),urgent,open_count,0]):
        c.markdown(f'<div class="metric"><small>{label}</small><h2>{val}</h2></div>',unsafe_allow_html=True)
    st.subheader('Recent sample complaints')
    st.dataframe(complaints.head(8),use_container_width=True,hide_index=True)
    st.info('The existing Python sorting rules are kept in rules.py and ticket_sorter.py. Use Submit Complaint to classify a new issue.')
elif page=='Submit Complaint':
    st.subheader('Create a maintenance complaint')
    with st.form('ticket_form'):
        complaint=st.text_area('Describe the issue',placeholder='Example: Water is leaking from the bathroom ceiling in A105...',height=130)
        name=st.text_input('Student name (optional)'); contact=st.text_input('Contact / room details (optional)')
        submitted=st.form_submit_button('Sort complaint',type='primary',use_container_width=True)
    if submitted:
        if not complaint.strip(): st.warning('Please describe the complaint first.')
        else:
            classifier,label,prompt_chars=core.build_classifier(True,BASE/'system_prompt.txt')
            stats=core.new_stats()
            result=core.analyse_complaint(complaint,classifier,stats,'WEB')
            st.session_state.submitted.insert(0,{'complaint':complaint,'name':name,'contact':contact,'result':result,'status':'Open'})
            st.success('Complaint analyzed using the project’s existing sorting pipeline.')
            st.json(result)
elif page=='Ticket Queue':
    st.subheader('Ticket queue')
    if not st.session_state.submitted: st.caption('No web-submitted tickets yet. Existing project tickets are shown below.')
    if st.session_state.submitted:
        rows=[]
        for x in st.session_state.submitted:
            r=x['result']; rows.append({'Complaint':x['complaint'],'Room':r.get('room','—'),'Issue':r.get('issue','—'),'Urgent':r.get('urgent','—'),'Status':x['status']})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    st.markdown('#### Existing open tickets')
    st.dataframe(open_tickets,use_container_width=True,hide_index=True)
elif page=='About':
    st.subheader('About this application')
    st.write('A modern web interface for the uploaded Hostel Maintenance Ticket Sorter. The app calls the original classification, validation, room-check, safety-net, routing and due-date logic rather than replacing it.')
    st.write('This web demo uses the project’s offline mock classifier by default. Configure the provider and API key in `.env` to enable real LLM classification. The warden remains responsible for assigning and closing work.')
