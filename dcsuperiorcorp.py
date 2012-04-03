from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from BeautifulSoup import BeautifulSoup

import sys
import os
import csv
import re
import logging

from name_cleaver import IndividualNameCleaver, OrganizationName

re_casenum = re.compile(r"(\d{4} \w{1,5} \d{6}\s?[\w\(\)]{0,6}): ")


class DCCourtCorpScraper(object):
    
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

        inputElement = self.driver.find_element_by_name("appData:searchform:jspsearchpage:companyName")
        inputElement.clear()
        inputElement.send_keys(full)

        self.driver.find_element_by_name("appData:searchform:jspsearchpage:submitSearch").click()

        #if we're still on the same page, then there were no criminal results
        try:
            inputElement = self.driver.find_element_by_name("appData:searchform:jspsearchpage:lastName")
            self.summary.writerow( ['',namecleave.name,'','',full,'','NO MATCH'] )
        except NoSuchElementException:
            self.scrollPages(namecleave,full)
            
        self.existing.append( [namecleave.name,'',''] )


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
                if self.goodEnoughMatch(namecleave,name):
                    ourguy = True
                    nameasreferenced.append(name)
                    if role not in roleasreferenced: roleasreferenced.append(role)
                elif alias and self.goodEnoughMatch(namecleave,alias):
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
                    self.docket.writerow( [casenum,namecleave.name,'',''] + list((i,date,event.strip(),message.strip())) )
                    i = i-1
                    
                charge = message
         
                namesused = '; '.join(nameasreferenced)
                roles = '; '.join(roleasreferenced)
         
                self.summary.writerow( list((casenum,namecleave.name,'','',full,namesused,roles,charge,casetype,datefile,casestatus,datestatus,casedisposition,datedisposition)) )


            if not soup.find('input',{'name':"appData:detailsform:jspdetailspage:prevNext:bottomNext"}):
                #there are no more cases for this person
                if not atleastoneprinted:
                    self.summary.writerow( ['',namecleave.name,'','',full,'','NO MATCH'] )
                break
        
            #scroll to next case for this person
            inputElement = self.driver.find_element_by_name("appData:detailsform:jspdetailspage:prevNext:bottomNext")
            inputElement.click()
            page = page+1
            
            if page==max_pages:
                self.summary.writerow( ['',namecleave.name,'','',full,'','MORE CASES MATCHING NAME SKIPPED (TOO MANY MATCHES)'] )
                
        self.driver.find_element_by_css_selector(".searchtoggleon").click()
                
    def goodEnoughMatch(self,n1,match):
        #the court's matching is intentionally weak, so this is important
        
        n2 = OrganizationName().new(match)
        return n1.kernel()==n2.kernel()
    


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
            if [n.name,'',''] in self.existing:
                logging.info('skipping %s, already present' % newname)
                continue
            try:
                self.lookupName(n,newname)
            except:
                goToIndex = self.driver.find_element_by_css_selector(".searchtoggleon")
                if goToIndex: goToIndex.click()
                print 'error'
                                

if __name__ == '__main__':
    
    logging.basicConfig(level=logging.INFO)
    
    #as the sole command line argument, pass the path to a list of names to look up. the output files will be created in that same directory
    infile = sys.argv[1]
    path = os.path.join( os.path.split(infile)[:-1] )[0]
    
    summary = os.path.join(path,'DCcourt_summaryC.csv')
    parties = os.path.join(path,'DCcourt_partiesC.csv')
    docket = os.path.join(path,'DCcourt_docketC.csv')  
   
    scraper = DCCourtCorpScraper(summary,parties,docket)
    
    fin = open(infile,'r').readlines()
    scraper.loopThroughNames(fin)

    scraper.driver.quit()
