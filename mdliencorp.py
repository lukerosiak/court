from BeautifulSoup import BeautifulSoup

import mechanize
import cookielib
import urllib2
import sys
import os
import csv
import re
import logging
from time import sleep
from name_cleaver import OrganizationName

re_content = reg = re.compile(r'.*Prompt|Value')



class MDLienCorpScraper(object):
    
    def __init__(self,summary):
         
        self.br = mechanize.Browser()
        cj = cookielib.LWPCookieJar()
        self.br.set_cookiejar(cj)
        
        self.goToStart()
        
        
        self.existing = [] #keep track of who we have so we can resume on error + don't look people up twice if our list has dupes
        if os.path.exists(summary):
            with open(summary,'r') as fin:
                existing_csv = csv.reader(fin)
                for line in existing_csv:
                    self.existing.append( line[1] )
        
        self.summary = csv.writer( open(summary,'a') )
        
        if not len(self.existing): #we're not appending, so write headers
            self.summary.writerow(['casenum','last','first','middle','search_fullname','names_incourt',\
            'plaintiff','defendant','county','status','amount','book','date','caseurl','comments'])
            
    def goToStart(self):
        self.br.open("http://casesearch.courts.state.md.us/inquiry/inquiry-index.jsp")
        self.br.select_form(nr=0)
        self.br.form['disclaimer']=['Y',]
        self.br.submit()
        
        #go to liens
        self.br.select_form(nr=0)
        self.br.form.set_all_readonly(False)
        self.br.form['judgmentFlag'] = 'true'
        self.br.submit()


    def lookupName(self,namecleave,full):
        #enter a name

        print self.br.response().read()
                
        self.br.select_form(nr=0)
        self.br.form['searchForm:companyIndicatorRadio'] = ["Y",]
        self.br.submit()
        
        print self.br.response().read()
        self.br.select_form(nr=0)

        try:
            self.br.form['searchForm:companyName'] = namecleave.name
        except:
            self.br.back()
            self.br.select_form(nr=0)
            self.br.form['searchForm:companyName'] = namecleave.name
        
        self.br.form['searchForm:filingStartDate'] = '01/01/1999'
        self.br.form['searchForm:filingEndDate'] = '01/01/2019'


        #self.br.form['countyName']=[
        
        self.br.submit()

        #if we're still on the same page, then there were no results
        html = self.br.response().read()
        if html.find("Sorry, but your search did not match any records.")>-1:
            self.summary.writerow( ['',namecleave.name,'','',full,'','NO MATCH'] )
        else: 
            self.scrollPages(namecleave,full)
            #return to search page to be ready for the next guy
            self.br.open("http://casesearch.courts.state.md.us/judgment/index.jsf")

            
        self.existing.append( namecleave.name )


    def scrollPages(self,namecleave,full):
        print '-----------------------scrollpages------------------------'
        
        
        #scroll through the list of individual cases that come up as matching an individual's name
        
        def addToList(all_rows):
            html = self.br.response().read()
            print html
            soup = BeautifulSoup(html)
            rows = soup.find('tbody',{'id':'_id0:data:tbody_element'}).findAll('tr') 

            for row in rows:
                all_rows.append(row)
            return all_rows
            
        all_rows = addToList([]) #combine multiple pages of results into one
            
        html = self.br.response().read()
        soup = BeautifulSoup(html)    
            
        
        pagelinks = soup.findAll('a',{'id':re.compile("_id0:scrollidx\d+")})
        if pagelinks: #there are multiple pages of possible cases
            for pagelink in pagelinks[1:]:
                self.br.select_form(nr=0)
                self.br.form.set_all_readonly(False)
                pagenum = pagelink.string

                self.br.form['_id0:_idcl'] = '_id0:scrollidx' + pagenum
                self.br.form['_id0:scroll'] = 'idx' + pagenum
                self.br.submit()
                all_rows = addToList(all_rows)
 

        print all_rows

        #some of these matches will be ruled out as false positives. if all are ruled out, make a "no matches" note
        atleastoneprinted = False 
        for row in all_rows:
            cells = row.findAll('td')
            link = cells[0].a['id']
            casenum = cells[0].a.string
            (plaintiff,defendant,county,status,amount,book,date) = [x.text for x in cells[1:]]

            #if they're the plaintiff, we dont care about the case
            if self.goodEnoughMatch(namecleave,defendant):
                self.getDetail(namecleave,full,defendant,link,casenum,plaintiff,defendant,county,status,amount,book,date)
                atleastoneprinted = True 
                    
        if not atleastoneprinted:
            print "no matches for %s in %s" % (full,defendant)
            self.summary.writerow( ['',namecleave.name,'','',full,'','NO MATCH'] )

    def getDetail(self,namecleave,full,incourt,link,casenum,plaintiff,defendant,county,status,amount,book,date):  
        print '-----------------------getdetail------------------------'
    
        self.br.select_form(nr=0)
        
        print self.br.response().read()
        self.br.form.set_all_readonly(False)
        try:
            self.br.form['_id0:_idcl'] = link
        except:
            print 'adding idcl'
            self.br.form.new_control('text','_id0:_idcl',{'value':''})
            self.br.form.fixup()

        self.br.submit()        
        
        html = self.br.response().read()
        soup = BeautifulSoup(html)
        
        content = soup.findAll('span')
        pairs = []
        key = []
        value = []
        for c in content:
            s = c.text or ''
            if c.a:
                s = c.a['href']
            if c.get('class') and c['class'].endswith('Prompt'): #key
                if len(value): #last pair done, on to a new one
                    pairs.append([' '.join(key), ' '.join(value).replace('\n','')])
                    key = []
                    value = []
                key.append(s)
            else:
                value.append(s)
            
        
        summary = {'caseurl':'','comments':''}
        for pair in pairs:
            if pair[0]=='Judgment Comments:': summary['comments'] = pair[1]
            if pair[0]=='Case Number:': summary['caseurl'] = pair[1]
        

        summaryrow = [casenum,namecleave.name,'','',full,incourt] \
            + [plaintiff,defendant,county,status,amount,book,date] \
            + [summary['caseurl'], summary['comments']]

        self.summary.writerow( summaryrow )

        print summaryrow

        self.br.back()
                
    def goodEnoughMatch(self,n1,match):
        #the court's matching is intentionally weak, so this is important
        
        n2 = OrganizationName().new(match)
        
        return n1.kernel().upper()==n2.kernel().upper()
    

    def loopThroughNames(self,names):
        
        endjunk = """assns Associations assn Association cmte Committee cltn Coalition inst Institute corp Corporation co Company fedn Federation fed Federal Company USA assoc Associates natl National nat'l intl International inc Incorporated llc llp lp plc ltd limited""".lower().split()

        for name in names:
            name = name.strip()
            newname = name
            for junk in endjunk:
                if newname.lower().endswith(' '+junk):
                    newname = newname[:-len(' '+junk)]
            if len(newname.split(','))>1:
                newname = newname.split(',')[0]

            logging.info(newname)
            n = OrganizationName().new(name)
            if n.name in self.existing:
                logging.info('skipping %s, already present' % newname)
                continue
            try:
                self.lookupName(n,newname)
            except:
                self.goToStart()
                self.lookupName(n,newname)
        
            sleep(.15)


if __name__ == '__main__':
    
    logging.basicConfig(level=logging.INFO)
    
    #as the sole command line argument, pass the path to a list of names to look up. the output file will be created in that same directory
    infile = sys.argv[1]
    path = os.path.join( os.path.split(infile)[:-1] )[0]
    
    summary = os.path.join(path,'mdliencorp.csv')
   
    scraper = MDLienCorpScraper(summary)
    
    fin = open(infile,'r').readlines()   
    
    scraper.loopThroughNames(fin)

