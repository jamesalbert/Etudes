from flask import Flask, jsonify, request, session, redirect, url_for
from peewee import MySQLDatabase, Model, TextField, CharField
from requests import Session, codes
from bs4 import BeautifulSoup
from itertools import product
import functools
import peewee
import pickle
import json
import ast


app = Flask(__name__)
host = 'https://myetudes.org/portal/'
db = MySQLDatabase('etudes', **{'user': 'root'})


'''
 DB Classes/Functions
'''

class UnknownField(object):
    pass


class BaseModel(Model):
    class Meta:
        database = db


class Sessions(BaseModel):
    json = TextField(null=True)
    session = TextField()
    username = CharField(max_length=9)

    class Meta:
        db_table = 'sessions'


def user_present(uname):
    try:
        Sessions.get(Sessions.username==uname)
        return True
    except peewee.DoesNotExist:
        return False


def session_present(uname):
    try:
        user = Sessions.get(Sessions.username==uname)
        s = user.session
        if s:
            return True

        return False
    except peewee.DoesNotExist:
        return False
    except Exception as e:
        return {'error': e.message}


def update_json(j):
    try:
        uname = session['username']
        Sessions.update(json=j)\
                    .where(Sessions.username==uname)\
                    .execute()
    except Exception as e:
        print e.message


def has_json():
    uname = session['username']
    gname = Sessions.username
    jsonstr = Sessions.get(gname==uname).json

    if jsonstr:
        return True

    return False


def get_session():
    try:
        uname = session['username']
        gname = Sessions.username
        db_res = Sessions.get(gname==uname)
        return pickle.loads(db_res.session)
    except Exception as e:
        print e.message


def report_json():
    try:
        uname = session['username']
        gname = Sessions.username
        return ast.literal_eval(Sessions.get(gname==uname).json)
    except Exception as e:
        print e.message


'''
 Native Functions
'''

def traverse(o, tree_types=(list, tuple)):
    '''Snippet from Jeremy Banks http://goo.gl/QAB5qr'''
    if isinstance(o, tree_types):
        for value in o:
            for subvalue in traverse(value):
                yield subvalue
    else:
        yield o


def wrong_creds(dom):
    if 'invalid login' in dom:
        return True

    return False


def logged_in(fn):
    try:
        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            try:
                '''redirect if not logged in'''
                uname = session.get('username')
                if not uname:
                    redirect(url_for('login_page'))

                if not has_json():
                    crawl()

                return fn(*args, **kwargs)
            except Exception as e:
                print {'error': e.message}

        return wrap
    except Exception as e:
        print e.message


'''
 Parsing Functions
'''

def find_assignments(res):
    '''
    parse assignments page, convert to json

    issue: add submission link
    '''
    try:
        '''init vars'''
        cols = ['type', 'title', 'status', 'open', 'due',
                'time limit', 'tries', 'started', 'finished', 'score']
        assignments = res.find_all('tr')
        a_tabs = []
        pairs = []
        ret = {}

        '''find every tab for each assignment'''
        assignments.pop(0)
        for each in assignments:
            a_tabs.append(each.find_all('td'))

        '''assign each tab with a column value'''
        for col, each in zip(cols*len(a_tabs), traverse(a_tabs)):
            if col == 'score':
                val = each.text.replace('Review','')
            else:
                val = each.text

            pairs.append({col: val.strip('\n') or 'assignment'})

        '''create json from list of column/value pairs'''
        for i, each in enumerate(pairs):
            index = i / 10
            ret.setdefault(index, {})
            ret[index].update(each)

        return ret

    except Exception as e:
        print e.message


def find_messages(res):
    '''parse messages page, convert to json'''
    try:
        '''init vars'''
        s = get_session()
        src = res.find('iframe', id='List').attrs['src']
        msg_str = s.get(src).text
        msg_dom = BeautifulSoup(msg_str)
        msg_body = msg_dom.find('ul', id='chatList')
        msgs = msg_body.find_all('li')
        msg_chl = []
        msg_json = {}

        '''gather name, date, and message'''
        for m in msgs:
            msgtext = m.text.strip().split('\t'*5)[1].strip()
            msgap = m.findChildren()
            msgap.append(msgtext)
            msg_chl.append(msgap)

        '''build message json'''
        for i, each in enumerate(msg_chl):
            date = each[1].text.strip()\
                       .replace('(','')\
                       .replace(')','')
            msg_json[i] = {'name': each[0].text,
                           'date': date,
                           'message': each[2]}

        return msg_json
    except Exception as e:
        return jsonify({'error': e.message})


def parse_gradebook(res):
    '''parse gradebook page, convert to json'''
    try:
        tr = res.find('tr')
        return {'status': '%s (unweighted)' % tr.text.replace(':', ': ')}
    except Exception as e:
        return jsonify({'error': e.message})


'''
 Crawling Algorithm
'''

def tabkey_shortener(k):
    return k.split(' ')[0].lower().split(',')[0]


def crawl(update=True, course_names=[]):
    '''
    get all links from dashboard

    update (bool): if True: update db, else: return
    '''
    try:
        '''init vars'''
        s = get_session()
        home_str = s.get(host).text
        home_dom = BeautifulSoup(home_str)
        links = home_dom.find_all('a')
        course_names = []
        course_links = {}

        '''grab only course links'''
        for l in links[5:]:
            title = l.attrs.get('title')
            if not title:
                continue

            link = l.attrs['href'].replace('/portal/', '')
            if 'worksite' in title:
                cli = l.text # len(course_links)
                course_links[cli] = {}
                course_links[cli]['link'] = '%s%s' % (host, link)
                if not course_names:
                    course_names.append(cli)


        '''
        find names/links of tabs
        issues:
            - clean up
        '''
        clii = course_links.iteritems()
        for cname, (l, b) in zip(course_names, clii):
        # for i, (l, b) in enumerate(course_links.iteritems()):
            url = b['link']
            main_str = s.get(url).text
            main_dom = BeautifulSoup(main_str)
            spans = main_dom.find_all('span')
            l_list = [x.text for x in spans if not x.attrs]
            h_i = l_list.index('Home')
            tabs = spans[h_i+3:]
            tab_links = [x.find_parent('a').attrs['href'].replace('/portal/','') for x in tabs]
            course_links[cname].update({tabkey_shortener(k): v
                                    for k, v in zip(l_list[h_i:], tab_links)})

        if update:
            update_json(str(course_links))
            return
        else:
            return course_links
    except Exception as e:
        return {'error': e.message}



'''
 Put Methods
'''

@app.route('/refresh', methods=['PUT'])
@logged_in
def refresh():
    '''
    refresh json in db
    NEEDS TESTING
    '''
    try:
        current = report_json()
        updated = crawl(update=False, course_names=current.values())
        if updated == current:
            return jsonify({'status': 'courses already up-to-date'})

        crawl(course_names=current.values())
        return jsonify({'status': 'courses up-to-date'})
    except Exception as e:
        return jsonify({'error': e.message})


@app.route('/rename', methods=['PUT'])
@logged_in
def rename():
    '''
    rename a course
    json:
        {
          "oldname": "val1",
          "newname": "val2"
        }
    '''
    try:
        updated = json.loads(request.data)
        oldname = updated.get('oldname')
        newname = updated.get('newname')
        current = report_json()
        current[newname] = current[oldname]
        del current[oldname]
        update_json(str(current))
        return jsonify({'status': 'course name updated'})
    except Exception as e:
        return jsonify({'error': e.message})


'''
 POST Methods
'''

@app.route('/login', methods=['POST'])
def login():
    '''
    Login to Etudes

    json {
      "eid": "username",
      "pw": "password"
    }
    '''
    try:
        '''get login creds'''
        creds = json.loads(request.data)
        uname = creds['eid']
        session['username'] = uname

        '''check if logged in'''
        if session_present(uname):
            return jsonify({'status': 'you are already logged in'})

        '''create session to store in db'''
        s = Session()
        url = '%s%s' % (host, 'xlogin')
        ret = s.post(url, data=creds)
        if ret.status_code == codes.ok:
            '''wrong username/password'''
            if wrong_creds(ret.text):
                return jsonify({'error': 'wrong username or password'})

            '''store session in db'''
            if user_present(uname):
                Sessions.update(session=pickle.dumps(s))\
                        .where(Sessions.username==uname).execute()
            else:
                Sessions.insert(session=pickle.dumps(s),
                                username=creds['eid']).execute()

            if not has_json():
                crawl()

            return jsonify({'status': 'you are logged in'})

        return jsonify({'status': False})
    except Exception as e:
        print e.message


@app.route('/sendchat', methods=['POST'])
@logged_in
def send_chat():
    '''
    Send chat message to specified course

    json {
      "message": "message"
    }
    '''
    try:
        s = get_session()
        payload = json.loads(request.data)
        payload['eventSubmit_doSend'] = 'x'
        url = payload.pop('url')
        res = s.post(url, data=payload)
        return jsonify({'status': 'message sent'})
    except KeyError as e:
        return jsonify({'error': 'url not given'})
    except Exception as e:
        return jsonify({'error': e.message})


'''
 DELETE Methods
'''

@app.route('/logout', methods=['DELETE'])
@logged_in
def logout():
    try:
        '''remove session from db'''
        uname = session['username']
        gname = Sessions.username
        if not session_present(uname):
            return jsonify({'status': 'already logged out'})
        Sessions.update(session='').where(gname==uname).execute()
        return jsonify({'status': 'logged out'})
    except Exception as e:
        return jsonify({'error': e.message})



'''
 GET Methods
'''

@app.route('/hit/<course>/<page>', methods=['GET'])
@logged_in
def hit(course, page):
    '''
    get json body from specified page belonging to specified course

    for available pages, refer to dict.'router'
    '''
    try:
        courses = report_json()
        url = '%s%s' % (host, courses[course][page])
        s = get_session()
        '''find iframe of specified tab'''
        dom_str = s.get(url).text
        dom = BeautifulSoup(dom_str)
        iframe = dom.find('iframe', attrs={'class': 'portletMainIframe'})
        '''follow iframe link'''
        src = iframe.attrs['src']
        res = BeautifulSoup(s.get(src).text)
        return jsonify(router[page](res))
    except Exception as e:
        return jsonify({'error': e.message})


router = {
    'assignments': find_assignments,
    'chat': find_messages,
    'gradebook': parse_gradebook
}



if __name__ == '__main__':
    app.secret_key = 'c25vd3B1c3N5'
    app.run()
