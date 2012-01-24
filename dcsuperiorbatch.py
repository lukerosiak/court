from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from BeautifulSoup import BeautifulSoup

import os
import csv
import re
import logging

from name_cleaver import IndividualNameCleaver

re_casenum = re.compile(r"(\d{4} \w{1,5} \d{6}\s?[\w\(\)]{0,6}): ")


class DCCourtScraper(object):
    
    def __init__(self,summary,parties,docket):
         
        #self.driver = webdriver.Remote("http://localhost:4444/wd/hub", webdriver.DesiredCapabilities.HTMLUNIT)
        self.driver = webdriver.Firefox()
        self.driver.implicitly_wait(9)
        
        self.existing = [] #keep track of who we have so we can resume on error + don't look people up twice if our list has dupes
        if os.path.exists(summary):
            with open(summary,'r') as fin:
                existing_csv = csv.reader(fin)
                for line in existing_csv:
                    self.existing.append( line[1:4] )
        
        self.summary = csv.writer( open(summary,'a') )
        self.parties = csv.writer( open(parties,'a') )
        self.docket = csv.writer( open(docket,'a') )
        
        if not len(self.existing): #we're not appending, so write headers
            self.summary.writerow(['casenum','last','first','middle','search_fullname','names_incourt','roles','charge','casetype','datefile','casestatus','datestatus','casedisposition','datedisposition'])
            self.parties.writerow(['casenum','search_name','name','alias','role','lawyer'])
            self.docket.writerow(['casenum','search_last','search_first','search_middle','num','date','event','message'])

    def lookupName(self,namecleave,full):
        #enter a name
        
        self.driver.get("https://www.dccourts.gov/cco/maincase.jsf")

        inputElement = self.driver.find_element_by_name("appData:searchform:jspsearchpage:lastName")
        inputElement.clear()
        inputElement.send_keys(namecleave.last)

        inputElement = self.driver.find_element_by_name("appData:searchform:jspsearchpage:firstName")
        inputElement.clear()
        inputElement.send_keys(namecleave.first)

        self.driver.find_element_by_name("appData:searchform:jspsearchpage:submitSearch").click()

        #if we're still on the same page, then there were no criminal results
        try:
            inputElement = self.driver.find_element_by_name("appData:searchform:jspsearchpage:lastName")
            self.summary.writerow( ['',namecleave.last,namecleave.first,namecleave.middle,full,'','NO MATCH'] )
        except NoSuchElementException:
            self.scrollPages(namecleave,full)
            
        self.existing.append( [namecleave.last,namecleave.first,namecleave.middle] )


    def scrollPages(self,namecleave,full):
        #scroll through the list of individual cases that come up as matching an individual's name

        self.driver.find_element_by_name("appData:resultsform:jspresultspage:dt1:j_id_id41pc6").click()

        #some of these matches will be ruled out as false positives. if all are ruled out, make a "no matches" note
        atleastoneprinted = False 
        
        page = 0
        max_pages = 70 #maximum cases before we figure this name is too generic
        while page < max_pages:
            self.driver.find_element_by_name("appData:detailsform:detailsPanelCollapsedState") 
            soup = BeautifulSoup(self.driver.page_source)
            
            
            titlestr = soup.find('div',{'class':'casesummaryheader'}).string
            titlespl = re_casenum.split(titlestr)
            title = titlespl[-2]
            casenum = titlespl[-2]
            summaryrows = soup.find('table',{'class':'casesummarydata'}).findAll('span',{'class':"columnDataSpacing"})
            (casetype,datefile,casestatus,datestatus,casedisposition,datedisposition) = [x.string for x in summaryrows]    
            
            partyout = []
            nameasreferenced = []
            roleasreferenced = []
            
            ourguy = False #try to eliminate false positives once we have a fuller name
            partyrows = soup.find('table',{'id':'appData:detailsform:jspdetailspage:partyInfo:partiesInfo'}).tbody.findAll('tr')
            for row in partyrows:
                rawrow = [x.string for x in row.findAll('td')]
                newrow = []
                for field in rawrow: 
                    if field: newrow.append(field.strip())
                    else: newrow.append('')
                (name,alias,role,lawyer) = newrow
                partyout.append( [casenum,full] + list((name,alias,role,lawyer)) )
                #this the guy we care about?
                if name.split(', ')>1 and self.goodEnoughMatch(namecleave,name):
                    ourguy = True
                    nameasreferenced.append(name)
                    if role not in roleasreferenced: roleasreferenced.append(role)
                elif alias and alias.split(', ')>1 and self.goodEnoughMatch(namecleave,alias):
                    ourguy = True
                    nameasreferenced.append(alias)
                    if role not in roleasreferenced: roleasreferenced.append(role)
                    
            if not ourguy:
                print "no matches for %s in %s" % (full,[x[2] for x in partyout])
                        
            if ourguy: #sufficiently good match, so do write the records to the CSVs
                atleastoneprinted = True
                for row in partyout: self.parties.writerow( row )
                    
            
                docketrows = soup.find('tbody',{'id':'appData:detailsform:jspdetailspage:docketInfo:DocketsInfo:tbody_element'}).findAll('tr')
                i = len(docketrows)
                for row in docketrows:
                    (date,event,message) = [y.decode('utf-8','ignore').strip() for y in [x.string or '' for x in row.findAll('td')]]
                    self.docket.writerow( [casenum,namecleave.last,namecleave.first,namecleave.middle] + list((i,date,event.strip(),message.strip())) )
                    i = i-1
                    
                charge = message
         
                namesused = '; '.join(nameasreferenced)
                roles = '; '.join(roleasreferenced)
         
                self.summary.writerow( list((casenum,namecleave.last,namecleave.first,namecleave.middle,full,namesused,roles,charge,casetype,datefile,casestatus,datestatus,casedisposition,datedisposition)) )


            if not soup.find('input',{'name':"appData:detailsform:jspdetailspage:prevNext:bottomNext"}):
                #there are no more cases for this person
                if not atleastoneprinted:
                    self.summary.writerow( ['',namecleave.last,namecleave.first,namecleave.middle,full,'','NO MATCH'] )
                break
        
            #scroll to next case for this person
            inputElement = self.driver.find_element_by_name("appData:detailsform:jspdetailspage:prevNext:bottomNext")
            inputElement.click()
            page = page+1
            
            if page==max_pages:
                self.summary.writerow( ['',namecleave.last,namecleave.first,namecleave.middle,full,'','MORE CASES MATCHING NAME SKIPPED (TOO MANY MATCHES)'] )
                
        self.driver.find_element_by_css_selector(".searchtoggleon").click()
                
    def goodEnoughMatch(self,n1,match):
        #the court's matching is intentionally weak, so this is important
        
        n2 = IndividualNameCleaver(match).parse()
        if n2.middle: n2.middle = n2.middle.replace('.','')
        if len(n2.last.split(' &amp; '))>1: #try to catch cases like 'DOWTIN &amp; ALL OTHER O, TANYA'
            n2.last = n2.last.split(' &amp; ')[0]
        if n1.last!=n2.last: return False 
        if n1.first!=n2.first:
            if (not n1.nick or n1.nick!=n2.first) or (not n2.nick or n2.nick!=n1.first):
                return False 
        if n1.middle and n2.middle:
            (middle1,middle2) = (n1.middle,n2.middle)
            if len(middle1)>1 and len(middle2)>1: 
                if middle1!=middle2: return False
            elif middle1[0]!=middle2[0]: return False
        
        #check jr's, sr's?    not doing not.
        return True
    

    def loopThroughNames(self,names):
        for name in names:
            name = name.strip()
            logging.info(name)
            n = IndividualNameCleaver(name).parse()
            if n.middle: 
                n.middle = n.middle.replace('.','') 
            else: 
                n.middle=''
            #(first,middle,last,suffix,nick) = (n.first, n.middle, n.last, n.suffix, n.nick)
            if [n.last,n.first,n.middle] in self.existing:
                logging.info('skipping %s, already present' % name)
                continue
            try:
                self.lookupName(n,name)
            except:
                goToIndex = self.driver.find_element_by_css_selector(".searchtoggleon")
                if goToIndex: goToIndex.click()
                print 'error'

if __name__ == '__main__':
    
    logging.basicConfig(level=logging.INFO)
    
    summary = 'summary.csv'  
    parties = 'parties.csv' 
    docket = 'docket.csv'  
   
    scraper = DCCourtScraper(summary,parties,docket)
    
    fin = open('roster.txt','r').readlines()
    scraper.loopThroughNames(fin)

    scraper.driver.quit()
